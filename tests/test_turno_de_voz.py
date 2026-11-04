"""Isolamento de audio e contrato de eventos do atendimento para a tela."""

import asyncio
import io
import json
import struct
import threading
import wave
from pathlib import Path

import pytest

import turno_de_voz
from agente.services import audio_service
from atendimento import Atendimento
from database import SessionLocal
from models import Pedido
import repositorio


def audio_wav(amostra):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<h", amostra) * 1600)
    return buffer.getvalue()


@pytest.mark.parametrize("etapa_concorrente", ["transcricao", "sintese"])
def test_chamadas_simultaneas_nao_trocam_audio(tmp_path, monkeypatch, etapa_concorrente):
    monkeypatch.setattr(audio_service, "PASTA_AUDIO", tmp_path)
    barreira = threading.Barrier(2)
    caminhos = []

    def transcrever(caminho, dica=None):
        caminhos.append(Path(caminho))
        if etapa_concorrente == "transcricao":
            barreira.wait(timeout=5)
        with wave.open(str(caminho)) as wav:
            return str(struct.unpack("<h", wav.readframes(1))[0])

    def sintetizar(texto, caminho=None):
        destino = Path(caminho) if caminho else tmp_path / "resposta.wav"
        destino.write_bytes(texto.encode())
        caminhos.append(destino)
        if etapa_concorrente == "sintese":
            barreira.wait(timeout=5)
        return destino

    class Socket:
        def __init__(self):
            self.audios = []

        async def send_json(self, mensagem):
            pass

        async def send_bytes(self, dados):
            self.audios.append(dados)

    class Atendimento:
        id_chamada = "chamada-concorrente"

        def dica_de_transcricao(self):
            return None

        def responder_com_eventos(self, texto):
            return {"texto": texto, "eventos": []}

    monkeypatch.setattr(turno_de_voz, "_agente", {
        "salvar_fala_em_wav": audio_service.salvar_fala_em_wav,
        "transcrever": transcrever,
        "sintetizar_resposta": sintetizar,
    })
    primeira, segunda = Socket(), Socket()

    async def executar():
        return await asyncio.gather(
            turno_de_voz.atender_turno(primeira, audio_wav(111), 0, 1, Atendimento()),
            turno_de_voz.atender_turno(segunda, audio_wav(222), 0, 1, Atendimento()),
        )

    fins = asyncio.run(executar())
    assert primeira.audios == [b"111"]
    assert segunda.audios == [b"222"]
    assert fins == [1600, 1600]
    assert all(not caminho.exists() for caminho in caminhos)


def test_nova_chamada_preserva_gravacao_anterior(tmp_path, monkeypatch):
    from rotas import voz

    monkeypatch.chdir(tmp_path)
    anterior = tmp_path / "audio_cliente_streaming.webm"
    anterior.write_bytes(b"evidencia anterior")

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, mensagem):
            pass

        async def receive(self):
            return {"type": "websocket.disconnect", "code": 1000}

    asyncio.run(voz.websocket_audio(Socket()))
    assert anterior.read_bytes() == b"evidencia anterior"


def test_transcricoes_vazias_recebem_orientacao_em_voz_sem_modelo(tmp_path, monkeypatch):
    from atendimento import Atendimento

    falas, eventos = [], []

    def sintetizar(texto, caminho):
        falas.append(texto)
        caminho.write_bytes(audio_wav(111))
        return caminho

    class Socket:
        async def send_json(self, mensagem):
            eventos.append(mensagem)

        async def send_bytes(self, dados):
            pass

    def nao_chamar(*args, **kwargs):
        raise AssertionError("Transcrição vazia não deve chamar modelo nem banco")

    atendimento = Atendimento(abrir_sessao=nao_chamar, conversar=nao_chamar)
    monkeypatch.setattr(turno_de_voz, "_agente", {
        "salvar_fala_em_wav": audio_service.salvar_fala_em_wav,
        "transcrever": lambda caminho, dica=None: "",
        "sintetizar_resposta": sintetizar,
    })
    for turno in (1, 2):
        asyncio.run(turno_de_voz.atender_turno(Socket(), audio_wav(111), 0, turno, atendimento))
    assert len(falas) == 2 and falas[0] != falas[1]
    assert all("?" in fala for fala in falas)
    assert len([e for e in eventos if e["tipo"] == "fim_audio"]) == 2


class Tela:
    def __init__(self):
        self.eventos = []

    async def send_json(self, evento):
        # O contrato deve ser JSON serializável, inclusive valores monetários.
        self.eventos.append(json.loads(json.dumps(evento)))

    async def send_bytes(self, audio):
        self.eventos.append({"tipo": "binario", "audio": audio})


@pytest.fixture
def chamada(db, monkeypatch, tmp_path):
    resposta = tmp_path / "resposta.wav"
    resposta.write_bytes(b"audio simulado")
    fala = {"texto": ""}

    def salvar(audio, inicio, caminho):
        caminho.write_bytes(audio)
        return caminho, inicio + 1

    agente = {
        "salvar_fala_em_wav": salvar,
        "transcrever": lambda caminho, dica=None: fala["texto"],
        "sintetizar_resposta": lambda texto, caminho=None: resposta,
    }
    monkeypatch.setattr(turno_de_voz, "carregar_agente", lambda: agente)

    def conversar(mensagens, formato=None):
        if mensagens[-1]["content"] == "obrigado":
            return json.dumps({"resposta": "De nada!", "itens": [],
                               "endereco": None, "fechar": False})
        return json.dumps({
            "resposta": "Vamos confirmar.",
            "itens": [{"produto": "Pizza Margherita", "quantidade": 2,
                       "observacao": "sem tomate"}],
            "endereco": "Rua Nova, 45", "fechar": True,
        })

    atendimento = Atendimento(abrir_sessao=SessionLocal, conversar=conversar)
    tela = Tela()
    numero = 0

    def falar(texto):
        nonlocal numero
        numero += 1
        fala["texto"] = texto
        tela.eventos.clear()
        asyncio.run(turno_de_voz.atender_turno(
            tela, b"entrada simulada", numero - 1, numero, atendimento))
        return list(tela.eventos)

    return atendimento, falar, agente


def evento_pedido(eventos):
    pedidos = [e for e in eventos if e["tipo"] == "pedido"]
    assert len(pedidos) == 1, "a tela precisa de um retrato do pedido por turno identificado"
    return pedidos[0]


def test_identificacao_e_rascunho_chegam_a_comanda(chamada, cpf_da_ana, db):
    atendimento, falar, _ = chamada
    antes = db.query(Pedido).count()
    identificado = evento_pedido(falar(cpf_da_ana))
    assert identificado["cliente"]["nome"] == "Ana Beatriz Moraes"
    assert identificado["cliente"]["telefone"] == "(19) 99812-4477"
    assert identificado["itens"] == []
    assert "cpf" not in json.dumps(identificado).lower()

    eventos = falar("duas margheritas sem tomate no pix, entrega na Rua Nova, 45")
    pedido = evento_pedido(eventos)
    assert pedido["turno"] == 2
    assert pedido["pedido_id"] is None
    assert pedido["itens"] == [{"produto": "Pizza Margherita", "quantidade": 2,
                                "preco_unitario": "66.90", "observacao": "sem tomate"}]
    assert pedido["total"] == "133.80"
    assert pedido["forma_pagamento"] == "pix"
    assert pedido["endereco_entrega"] == "Rua Nova, 45"
    assert not any(e["tipo"] == "pedido_salvo" for e in eventos)
    assert db.query(Pedido).count() == antes


@pytest.mark.parametrize("falha_voz", [False, True])
def test_confirmacao_chega_apos_gravar_mesmo_se_a_voz_falhar(
    chamada, cpf_da_ana, db, falha_voz,
):
    atendimento, falar, agente = chamada
    falar(cpf_da_ana)
    falar("duas margheritas no pix")
    falar("finalizar")
    if falha_voz:
        def falhar(texto, caminho=None):
            raise RuntimeError("sintese indisponivel")
        agente["sintetizar_resposta"] = falhar

    eventos = falar("sim")
    pedido = evento_pedido(eventos)
    salvos = [e for e in eventos if e["tipo"] == "pedido_salvo"]
    assert len(salvos) == 1
    gravado = db.get(Pedido, salvos[0]["pedido_id"])
    assert gravado is not None
    assert pedido["pedido_id"] == gravado.id
    assert pedido["total"] == salvos[0]["total"] == str(gravado.total) == "133.80"
    assert pedido["itens"][0]["quantidade"] == 2
    assert atendimento.carrinho == []
    tipos = [e["tipo"] for e in eventos]
    assert tipos.index("pedido") < tipos.index("pedido_salvo")
    assert tipos.index("pedido_salvo") < tipos.index("erro" if falha_voz else "audio_resposta")

    # O próximo turno não pode apagar a venda nem anunciar outra gravação.
    seguintes = falar("sim")
    assert evento_pedido(seguintes)["pedido_id"] == gravado.id
    assert not any(e["tipo"] == "pedido_salvo" for e in seguintes)
    despedida = falar("obrigado")
    assert evento_pedido(despedida)["pedido_id"] == gravado.id
    assert evento_pedido(despedida)["total"] == "133.80"
    assert not any(e["tipo"] == "pedido_salvo" for e in despedida)
    novo = evento_pedido(falar("duas margheritas no pix"))
    assert novo["pedido_id"] is None


def test_falha_no_banco_nao_anuncia_pedido_salvo(chamada, cpf_da_ana, db, monkeypatch):
    _, falar, _ = chamada
    falar(cpf_da_ana)
    falar("duas margheritas no pix")
    falar("finalizar")
    antes = db.query(Pedido).count()

    def falhar(*args, **kwargs):
        raise RuntimeError("banco indisponivel")

    monkeypatch.setattr(repositorio, "salvar_pedido", falhar)
    eventos = falar("sim")
    assert evento_pedido(eventos)["pedido_id"] is None
    assert not any(e["tipo"] == "pedido_salvo" for e in eventos)
    assert db.query(Pedido).count() == antes


class TestAtendenteFalaPrimeiro:
    def _conexao(self):
        class Conexao:
            def __init__(self):
                self.enviados = []

            async def send_json(self, evento):
                self.enviados.append(evento)

            async def send_bytes(self, dados):
                self.enviados.append(dados)
        return Conexao()

    def test_saudacao_vai_em_texto_e_voz_e_fica_guardada(self, monkeypatch, tmp_path):
        chamadas = []

        def sintetizar(texto, caminho):
            chamadas.append(texto)
            caminho.write_bytes(b"voz")
            return caminho

        monkeypatch.setattr("agente.services.piper_service.sintetizar_resposta", sintetizar)
        monkeypatch.setattr(turno_de_voz, "_saudacoes", {})
        primeira, segunda = self._conexao(), self._conexao()
        asyncio.run(turno_de_voz.saudar(primeira, Atendimento()))
        asyncio.run(turno_de_voz.saudar(segunda, Atendimento()))

        assert primeira.enviados[0]["tipo"] == "transcricao"
        assert "Seja bem-vindo" in primeira.enviados[0]["texto"]
        assert [e["tipo"] for e in primeira.enviados if isinstance(e, dict)][1:] == ["audio_resposta", "fim_audio"]
        assert b"voz" in primeira.enviados
        assert segunda.enviados == primeira.enviados
        assert len(chamadas) == 1

    def test_falha_na_voz_mantem_o_texto_e_a_chamada(self, monkeypatch):
        def falha(texto, caminho):
            raise RuntimeError("piper fora")

        monkeypatch.setattr("agente.services.piper_service.sintetizar_resposta", falha)
        monkeypatch.setattr(turno_de_voz, "_saudacoes", {})
        conexao = self._conexao()
        asyncio.run(turno_de_voz.saudar(conexao, Atendimento()))
        assert [e["tipo"] for e in conexao.enviados] == ["transcricao", "estado"]
        assert conexao.enviados[1]["etapa"] == "ouvindo"
