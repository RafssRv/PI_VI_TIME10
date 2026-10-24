"""Contrato da rota de voz usando frames ASGI e o WebSocket real do Starlette."""

import asyncio
import json

import pytest
import main
from rotas import voz


INICIO = {"tipo": "iniciar_chamada", "versao_protocolo": 1,
          "formato_audio": "audio/webm;codecs=opus", "chunk_ms": 250}
FIM = {"tipo": "fim_da_fala", "turno": 1, "duracao_ms": 2100}


def texto(dados):
    return {"type": "websocket.receive", "text": json.dumps(dados, ensure_ascii=False)}


def audio(dados=b"audio"):
    return {"type": "websocket.receive", "bytes": dados}


@pytest.fixture
def executar(monkeypatch, tmp_path):
    # A rota ainda grava o áudio de diagnóstico; nunca tocar nos arquivos locais.
    monkeypatch.chdir(tmp_path)
    turnos = []

    async def atender(websocket, dados, inicio, turno, atendimento):
        turnos.append((bytes(dados), turno))
        await websocket.send_json({"tipo": "estado", "etapa": "ouvindo", "turno": turno})
        return inicio + 1

    monkeypatch.setattr(voz, "atender_turno", atender)

    def rodar(frames, esperar=False):
        async def sessao():
            entradas = iter([{"type": "websocket.connect"}, *frames])
            saidas = []

            async def receber():
                try:
                    return next(entradas)
                except StopIteration:
                    if esperar:
                        await asyncio.Event().wait()
                    return {"type": "websocket.disconnect", "code": 1000}

            async def enviar(frame):
                saidas.append(frame)

            scope = {"type": "websocket", "path": "/ws/falar", "root_path": "",
                     "query_string": b"", "headers": [], "scheme": "ws"}
            await asyncio.wait_for(main.app(scope, receber, enviar), timeout=1)
            eventos = [json.loads(f["text"]) for f in saidas
                       if f["type"] == "websocket.send" and f.get("text", "").startswith("{")]
            fechamentos = [f["code"] for f in saidas if f["type"] == "websocket.close"]
            return eventos, fechamentos

        return asyncio.run(sessao())

    rodar.turnos = turnos
    rodar.arquivo = tmp_path / "audio_cliente_streaming.webm"
    return rodar


def conferir_rejeicao(resultado, codigo=1008):
    eventos, fechamentos = resultado
    erros = [e for e in eventos if e["tipo"] == "erro"]
    assert len(erros) == 1
    assert erros[0]["fatal"] is True
    assert erros[0]["onde"] == "protocolo"
    assert fechamentos == [codigo]


@pytest.mark.parametrize("entrada", ["[]", "null", "123", "true", '"texto"', "{", '{}',
                                    '{"tipo": []}', '{"tipo": "desconhecido"}'])
def test_json_invalido_retorna_erro_controlado(executar, entrada):
    conferir_rejeicao(executar([{"type": "websocket.receive", "text": entrada}]))
    assert executar.turnos == []


@pytest.mark.parametrize("campo,valor", [
    ("versao_protocolo", 2), ("versao_protocolo", True), ("versao_protocolo", "1"),
    ("formato_audio", "text/plain"), ("formato_audio", []),
    ("chunk_ms", 0), ("chunk_ms", True), ("chunk_ms", "250"), ("chunk_ms", 10001),
])
def test_abertura_com_campos_invalidos_nao_inicia_chamada(executar, campo, valor):
    conferir_rejeicao(executar([texto({**INICIO, campo: valor})]))


@pytest.mark.parametrize("mensagem", [
    {"tipo": "iniciar_chamada"}, {**INICIO, "extra": "inesperado"},
    {"tipo": "fim_da_fala", "turno": 1},
    {**FIM, "turno": True}, {**FIM, "turno": "1"}, {**FIM, "turno": -1},
    {**FIM, "duracao_ms": 0}, {**FIM, "duracao_ms": 1.5},
    {"tipo": "resposta_tocada", "turno": None},
    {"tipo": "timeout", "turno": 0}, {"tipo": "encerrar_chamada", "motivo": []},
])
def test_controles_incompletos_ou_com_tipos_errados_sao_rejeitados(executar, mensagem):
    conferir_rejeicao(executar([texto(INICIO), texto(mensagem)]))
    assert executar.turnos == []


@pytest.mark.parametrize("frame", [audio(), texto(FIM), texto({"tipo": "timeout", "turno": 1})])
def test_nao_processa_frames_antes_da_abertura(executar, frame):
    conferir_rejeicao(executar([frame]))
    assert executar.turnos == []
    assert not executar.arquivo.exists() or executar.arquivo.read_bytes() == b""


@pytest.mark.parametrize("formato", ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus",
                                     "audio/mp4", "audio/mp4;codecs=mp4a.40.2"])
def test_fluxo_do_frontend_aceita_audio_e_dois_turnos(executar, formato):
    eventos, fechamentos = executar([
        texto({**INICIO, "formato_audio": formato}), audio(b"cabecalho"), texto(FIM),
        texto({"tipo": "resposta_tocada", "turno": 1}), audio(b"continuacao"),
        texto({**FIM, "turno": 2}), texto({"tipo": "timeout", "turno": 2}),
        texto({"tipo": "encerrar_chamada", "motivo": "cliente_desligou"}),
    ])
    assert not any(e["tipo"] == "erro" for e in eventos)
    assert fechamentos == [1000]
    assert executar.turnos == [(b"cabecalho", 1), (b"cabecalhocontinuacao", 2)]


def test_turno_repetido_nao_reprocessa_audio(executar):
    conferir_rejeicao(executar([texto(INICIO), audio(), texto(FIM), texto(FIM)]))
    assert executar.turnos == [(b"audio", 1)]


def test_turno_sem_audio_novo_nao_chama_pipeline(executar):
    conferir_rejeicao(executar([texto(INICIO), texto(FIM)]))
    assert executar.turnos == []


@pytest.mark.parametrize("tipo", ["resposta_tocada", "timeout"])
def test_aviso_de_turno_nao_processado_e_rejeitado(executar, tipo):
    conferir_rejeicao(executar([texto(INICIO), texto({"tipo": tipo, "turno": 1})]))


def test_abertura_repetida_nao_reinicia_limites(executar):
    conferir_rejeicao(executar([texto(INICIO), texto(INICIO)]))


def test_limite_de_controle_conta_bytes_utf8(executar):
    conferir_rejeicao(executar([texto({"tipo": "encerrar_chamada", "motivo": "á" * 2100})]), 1009)


def test_controle_no_limite_de_bytes_ainda_e_aceito(executar):
    inicio = json.dumps(INICIO)
    frame = {"type": "websocket.receive", "text": inicio + " " * (4096 - len(inicio))}
    eventos, fechamentos = executar([frame, texto({"tipo": "encerrar_chamada", "motivo": "fim"})])
    assert not any(e["tipo"] == "erro" for e in eventos)
    assert fechamentos == [1000]


def test_json_com_aninhamento_excessivo_nao_derruba_handler(executar):
    conferir_rejeicao(executar([{"type": "websocket.receive", "text": "[" * 1500 + "]" * 1500}]))


def test_bloco_grande_e_rejeitado_antes_de_gravar(executar, monkeypatch):
    monkeypatch.setattr(voz, "LIMITE_BLOCO_AUDIO_BYTES", 4)
    conferir_rejeicao(executar([texto(INICIO), audio(b"12345")]), 1009)
    assert executar.arquivo.read_bytes() == b""


def test_audio_no_limite_e_aceito_mas_excesso_acumulado_nao(executar, monkeypatch):
    monkeypatch.setattr(voz, "LIMITE_AUDIO_CHAMADA_BYTES", 5)
    conferir_rejeicao(executar([texto(INICIO), audio(b"123"), audio(b"45"), texto(FIM), audio(b"6")]), 1009)
    assert executar.arquivo.read_bytes() == b"12345"


def test_bloco_no_limite_e_aceito(executar, monkeypatch):
    monkeypatch.setattr(voz, "LIMITE_BLOCO_AUDIO_BYTES", 4)
    eventos, _ = executar([texto(INICIO), audio(b"1234"), texto(FIM)])
    assert not any(e["tipo"] == "erro" for e in eventos)
    assert executar.turnos == [(b"1234", 1)]


def test_conexao_silenciosa_expira_pelo_relogio_do_servidor(executar, monkeypatch):
    monkeypatch.setattr(voz, "DURACAO_MAXIMA_CHAMADA_S", 0.02)
    conferir_rejeicao(executar([], esperar=True))


def test_duracao_inclui_processamento_sem_admitir_outro_turno(executar, monkeypatch):
    monkeypatch.setattr(voz, "DURACAO_MAXIMA_CHAMADA_S", 0.02)

    async def lento(websocket, dados, inicio, turno, atendimento):
        executar.turnos.append(turno)
        await asyncio.sleep(0.03)
        return inicio + 1

    monkeypatch.setattr(voz, "atender_turno", lento)
    conferir_rejeicao(executar([texto(INICIO), audio(), texto(FIM), audio(), texto({**FIM, "turno": 2})]))
    assert executar.turnos == [1]
