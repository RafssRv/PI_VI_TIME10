"""
forma de pagamento como a pessoa fala ao telefone, traduzida para os quatro valores que a
coluna pedido.forma_pagamento aceita.
"""

import pytest

import repositorio


class TestFalaQueOSistemaEntende:
    @pytest.mark.parametrize(
        "falado,esperado",
        [
            ("pix", "pix"),
            ("no pix", "pix"),
            ("vou pagar no pix", "pix"),
            ("PIX", "pix"),
            ("Pix", "pix"),
            ("dinheiro", "dinheiro"),
            ("em dinheiro", "dinheiro"),
            ("dinheiro, troco para 100", "dinheiro"),
            ("em especie", "dinheiro"),
            ("credito", "cartao_credito"),
            ("cartao credito", "cartao_credito"),
            ("cartao de credito", "cartao_credito"),
            ("no cartao de credito", "cartao_credito"),
            ("Cartão de Crédito", "cartao_credito"),
            ("cartao_credito", "cartao_credito"),
            ("debito", "cartao_debito"),
            ("cartao de debito", "cartao_debito"),
            ("no debito", "cartao_debito"),
        ],
    )
    def test_traduz_para_o_valor_do_banco(self, falado, esperado):
        assert repositorio.interpretar_pagamento(falado) == esperado


class TestFalaQueViraPergunta:
    def test_cartao_sozinho_nao_chuta_entre_credito_e_debito(self):
        with pytest.raises(ValueError, match="credito ou no debito"):
            repositorio.interpretar_pagamento("cartao")

    def test_maquininha_tambem_e_ambigua(self):
        with pytest.raises(ValueError, match="credito ou no debito"):
            repositorio.interpretar_pagamento("maquininha")

    def test_cliente_que_citou_duas_formas_ainda_nao_decidiu(self):
        with pytest.raises(ValueError, match="mais de uma forma"):
            repositorio.interpretar_pagamento("dinheiro ou cartao de credito")

    def test_forma_que_a_pizzaria_nao_aceita(self):
        with pytest.raises(ValueError, match="nao reconhecida"):
            repositorio.interpretar_pagamento("boleto")

    def test_vazio_pergunta_em_vez_de_assumir(self):
        with pytest.raises(ValueError, match="vazia"):
            repositorio.interpretar_pagamento("")


class TestNoPedido:
    def test_pedido_guarda_a_forma_canonica(self, db, ana):
        pedido = repositorio.salvar_pedido(
            db, ana.id, [{"produto": "margherita", "quantidade": 1}],
            forma_pagamento="Cartão de Crédito",
        )
        assert pedido.forma_pagamento == "cartao_credito"

    def test_pagamento_invalido_nao_grava_o_pedido(self, db, ana):
        from models import Pedido

        antes = db.query(Pedido).count()
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(
                db, ana.id, [{"produto": "margherita", "quantidade": 1}],
                forma_pagamento="boleto",
            )
        assert db.query(Pedido).count() == antes

    def test_pedido_pode_nascer_sem_forma_de_pagamento(self, db, ana):
        """o cliente ainda vai decidir; o pedido nasce aberto e alguem fecha depois."""
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert pedido.forma_pagamento is None
