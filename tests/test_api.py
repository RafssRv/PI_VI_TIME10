"""Contrato HTTP/WebSocket sem exigir modelos de IA ou PostgreSQL."""

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json", "/", "/app.js", "/style.css", "/teste"])
def test_rotas_disponiveis(client, path):
    assert client.get(path).status_code == 200


def test_documentacao_descreve_upload(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/falar" in schema["paths"]


def test_upload_de_teste_devolve_os_bytes(client):
    resposta = client.post("/api/v1/falar", files={"audio": ("voz.wav", b"audio de teste", "audio/wav")})
    assert resposta.status_code == 200
    assert resposta.content == b"audio de teste"


def test_nome_do_upload_nao_e_um_caminho(client):
    resposta = client.post("/api/v1/falar", files={"audio": ("../../voz.wav", b"teste", "audio/wav")})
    assert resposta.status_code == 200
    assert resposta.content == b"teste"


def test_upload_vazio_e_recusado(client):
    assert client.post("/api/v1/falar", files={"audio": ("vazio.wav", b"", "audio/wav")}).status_code == 400


def test_upload_limitado(client, monkeypatch):
    monkeypatch.setattr(main, "LIMITE_AUDIO_BYTES", 8)
    assert client.post("/api/v1/falar", files={"audio": ("grande.wav", b"x" * 9, "audio/wav")}).status_code == 413


@pytest.mark.parametrize("controle", ["null", "[]", "1", '"texto"', "{invalido"])
def test_controle_invalido_nao_derruba_socket(client, controle):
    with client.websocket_connect("/ws/falar") as ws:
        assert ws.receive_json()["tipo"] == "pronto"
        ws.send_text(controle)
        assert ws.receive_json()["tipo"] == "erro"
        ws.send_json({"tipo": "encerrar_chamada"})
        assert ws.receive_json()["tipo"] == "chamada_encerrada"


def test_audio_websocket_limitado(client, monkeypatch):
    monkeypatch.setattr(main, "LIMITE_AUDIO_BYTES", 8)
    with client.websocket_connect("/ws/falar") as ws:
        ws.receive_json()
        ws.send_bytes(b"x" * 9)
        assert ws.receive_json()["fatal"] is True


def test_socket_executa_turno_e_mantem_contexto_por_chamada(client, monkeypatch):
    contextos = []

    async def turno(ws, audio, inicio, numero, historico):
        contextos.append((bytes(audio), inicio, numero, list(historico)))
        historico.append({"role": "user", "content": str(numero)})
        await ws.send_json({"tipo": "estado", "etapa": "ouvindo"})
        return inicio + 10

    monkeypatch.setattr(main, "atender_turno", turno)
    for chamada in range(2):
        with client.websocket_connect("/ws/falar") as ws:
            ws.receive_json()
            for numero in (1, 2):
                ws.send_bytes(b"audio")
                ws.send_json({"tipo": "fim_da_fala", "turno": numero})
                assert ws.receive_json()["etapa"] == "ouvindo"
            ws.send_json({"tipo": "encerrar_chamada"})
            ws.receive_json()
    assert contextos[0] == (b"audio", 0, 1, [])
    assert contextos[1][1:] == (10, 2, [{"role": "user", "content": "1"}])
    assert contextos[2][3] == []
