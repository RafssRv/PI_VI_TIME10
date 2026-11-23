"""
andamento do pedido no painel: aberto -> em_preparo -> saiu_entrega -> entregue, ou cancelado
antes de sair. o banco recusa status fora da lista, e a rota so deixa dar um passo por vez.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

import painel
import repositorio
from models import Pedido

ITEM = [{"produto": "margherita", "tamanho": "grande", "quantidade": 1, "observacao": "sem cebola"}]


@pytest.fixture
def novo(db, ana):
    return repositorio.salvar_pedido(db, ana.id, ITEM, forma_pagamento="dinheiro", troco_para=100,
                                     endereco_entrega="Rua Nova, 45")


class TestMudarStatus:
    def test_anda_um_passo_por_vez_ate_entregue(self, db, novo):
        assert novo.status == "aberto"
        for status in ("em_preparo", "saiu_entrega", "entregue"):
            assert repositorio.mudar_status(db, novo.id, status).status == status
        assert db.get(Pedido, novo.id).status == "entregue"

    @pytest.mark.parametrize("passos, proibido", [
        ([], "saiu_entrega"),                                # pular o preparo
        (["em_preparo"], "aberto"),                          # voltar
        (["em_preparo", "saiu_entrega"], "cancelado"),       # cancelar depois de sair
        (["em_preparo", "saiu_entrega", "entregue"], "em_preparo"),
        ([], "inventado"),
    ])
    def test_passo_que_nao_vale(self, db, novo, passos, proibido):
        for status in passos:
            repositorio.mudar_status(db, novo.id, status)
        with pytest.raises(ValueError):
            repositorio.mudar_status(db, novo.id, proibido)

    @pytest.mark.parametrize("passos", [[], ["em_preparo"]])
    def test_cancela_antes_de_sair(self, db, novo, passos):
        for status in passos:
            repositorio.mudar_status(db, novo.id, status)
        assert repositorio.mudar_status(db, novo.id, "cancelado").status == "cancelado"

    def test_pedido_que_nao_existe(self, db):
        with pytest.raises(LookupError):
            repositorio.mudar_status(db, 999999, "em_preparo")

    def test_banco_recusa_status_fora_da_lista(self, db, novo):
        novo.status = "concluido"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


class TestEmAndamento:
    def test_lista_so_os_que_faltam_entregar(self, db, novo):
        ids = [p.id for p in repositorio.pedidos_em_andamento(db)]
        assert novo.id in ids
        # o historico do seed ja foi entregue: a cozinha nao ve pedido de semanas atras
        assert all(p.status in ("aberto", "em_preparo", "saiu_entrega") for p in repositorio.pedidos_em_andamento(db))
        repositorio.mudar_status(db, novo.id, "cancelado")
        assert novo.id not in [p.id for p in repositorio.pedidos_em_andamento(db)]

    def test_json_tem_o_que_a_cozinha_precisa_e_nada_sensivel(self, db, novo):
        dados = painel.montar_em_andamento(repositorio.pedidos_em_andamento(db), datetime.now().astimezone())
        cartao = next(p for p in dados["pedidos"] if p["id"] == novo.id)
        assert cartao["cliente"] == "Ana"
        assert cartao["itens"] == [{"quantidade": 1, "produto": "Pizza Margherita grande", "observacao": "sem cebola"}]
        assert (cartao["forma_pagamento"], cartao["troco_para"]) == ("dinheiro", "100.00")
        assert cartao["endereco_entrega"] == "Rua Nova, 45"
        texto = json.dumps(dados)
        assert "cpf" not in texto and "telefone" not in texto


class TestRotas:
    @pytest.fixture
    def app(self, monkeypatch):
        import importlib.util
        import config
        import main

        monkeypatch.setattr(config, "AMBIENTE", "dev")
        spec = importlib.util.spec_from_file_location("aplicativo_status", main.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo.app

    def _post(self, app, pedido_id, corpo):
        from test_rotas import requisitar

        return requisitar(app, "/api/admin/pedidos/{}/status".format(pedido_id), metodo="POST",
                          corpo=json.dumps(corpo).encode(), headers=[(b"content-type", b"application/json")])

    def test_lista_e_avanca(self, app, db, novo):
        from test_rotas import requisitar

        status, corpo = requisitar(app, "/api/admin/pedidos/andamento")
        assert status == 200 and novo.id in [p["id"] for p in json.loads(corpo)["pedidos"]]
        status, corpo = self._post(app, novo.id, {"status": "em_preparo"})
        assert status == 200 and json.loads(corpo) == {"id": novo.id, "status": "em_preparo"}

    def test_respostas_de_erro(self, app, db, novo):
        assert self._post(app, novo.id, {"status": "entregue"})[0] == 409
        assert self._post(app, 999999, {"status": "em_preparo"})[0] == 404
        assert self._post(app, novo.id, {})[0] == 422

    def test_rotas_nao_existem_fora_de_desenvolvimento(self, monkeypatch):
        import importlib.util
        import config
        import main
        from test_rotas import requisitar

        monkeypatch.setattr(config, "AMBIENTE", "producao")
        spec = importlib.util.spec_from_file_location("aplicativo_producao", main.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        assert requisitar(modulo.app, "/api/admin/pedidos/andamento")[0] == 404
