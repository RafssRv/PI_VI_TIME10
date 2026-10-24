"""Integra atendimento real, banco de teste e eventos enviados para a tela."""

import asyncio
import json

import pytest

from atendimento import Atendimento
from database import SessionLocal
from models import Pedido
import repositorio
import turno_de_voz


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
    agente = {
        "salvar_fala_em_wav": lambda audio, inicio: ("cliente.wav", inicio + 1),
        "transcrever": lambda caminho: fala["texto"],
        "sintetizar_resposta": lambda texto: resposta,
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
    if falha_voz:
        def falhar(texto):
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
    antes = db.query(Pedido).count()

    def falhar(*args, **kwargs):
        raise RuntimeError("banco indisponivel")

    monkeypatch.setattr(repositorio, "salvar_pedido", falhar)
    eventos = falar("sim")
    assert evento_pedido(eventos)["pedido_id"] is None
    assert not any(e["tipo"] == "pedido_salvo" for e in eventos)
    assert db.query(Pedido).count() == antes
