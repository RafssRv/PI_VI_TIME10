"""Rotas públicas e isolamento do diagnóstico por ambiente, via ASGI real."""

import asyncio
import importlib.util
import json
import pytest

import config
import main


@pytest.fixture
def aplicativo(monkeypatch):
    def carregar(ambiente):
        monkeypatch.setattr(config, "AMBIENTE", ambiente)
        spec = importlib.util.spec_from_file_location("aplicativo_de_teste", main.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.app
    return carregar


def requisitar(app, caminho, metodo="GET", corpo=b"", headers=()):
    async def executar():
        mensagens = []

        async def receber():
            return {"type": "http.request", "body": corpo, "more_body": False}

        async def enviar(mensagem):
            mensagens.append(mensagem)

        await app({"type": "http", "http_version": "1.1", "method": metodo,
                   "scheme": "http", "path": caminho, "raw_path": caminho.encode(),
                   "root_path": "", "query_string": b"", "headers": list(headers),
                   "server": ("localhost", 3000), "client": ("127.0.0.1", 1234)}, receber, enviar)
        status = next(m["status"] for m in mensagens if m["type"] == "http.response.start")
        conteudo = b"".join(m.get("body", b"") for m in mensagens)
        return status, conteudo

    return asyncio.run(executar())


@pytest.mark.parametrize("ambiente", ["dev", "producao", "homolog"])
def test_health_e_frontend_continuam_acessiveis_de_outra_pasta(aplicativo, tmp_path, monkeypatch, ambiente):
    app = aplicativo(ambiente)
    monkeypatch.chdir(tmp_path)
    status, corpo = requisitar(app, "/health")
    assert status == 200 and json.loads(corpo)["status"] == "ok"
    assert requisitar(app, "/")[0] == 200
    status, corpo = requisitar(app, "/app.js")
    assert status == 200 and b"function aplicarMensagem" in corpo


@pytest.mark.parametrize("ambiente,esperado", [("dev", 200), ("producao", 404), ("homolog", 404)])
def test_diagnostico_so_e_servido_em_desenvolvimento(aplicativo, tmp_path, monkeypatch, ambiente, esperado):
    app = aplicativo(ambiente)
    monkeypatch.chdir(tmp_path)
    status, corpo = requisitar(app, "/teste")
    assert status == esperado
    if status == 200:
        assert b"iniciar_chamada" in corpo
    for caminho in ["/backend/teste_ws.html", "/scripts/diagnostico/teste_ws.html"]:
        assert requisitar(app, caminho)[0] == 404


def test_upload_permanece_na_rota_http(aplicativo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    corpo = (b"--teste\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"teste.webm\"\r\n"
             b"Content-Type: audio/webm\r\n\r\naudio de teste\r\n--teste--\r\n")
    status, recebido = requisitar(aplicativo("dev"), "/api/v1/falar", "POST", corpo,
                                  [(b"content-type", b"multipart/form-data; boundary=teste")])
    assert status == 200 and recebido == b"audio de teste"
    assert (tmp_path / "temp_teste.webm").read_bytes() == b"audio de teste"
