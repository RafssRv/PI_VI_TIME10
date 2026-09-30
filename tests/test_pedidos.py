"""
montagem e gravacao do pedido (RF09 e RF11), com a validacao contra o cardapio que o
RIA04 exige e a garantia de que um pedido grava inteiro ou nao grava.
"""

from decimal import Decimal

import pytest

import repositorio
from models import Pedido


def quantos_pedidos(db):
    return db.query(Pedido).count()


class TestPedidoQueDaCerto:
    def test_grava_itens_e_total(self, db, ana):
        pedido = repositorio.salvar_pedido(
            db, ana.id,
            [
                {"produto": "margherita", "quantidade": 2, "observacao": "sem cebola"},
                {"produto": "coca cola", "quantidade": 1},
            ],
            endereco_entrega="Rua das Palmeiras, 120",
            forma_pagamento="pix",
        )
        assert pedido.id is not None
        assert len(pedido.itens) == 2
        esperado = sum(item.preco_unitario * item.quantidade for item in pedido.itens)
        assert pedido.total == esperado

    def test_copia_o_preco_do_momento_da_venda(self, db, ana):
        """
        o preco vai para o item, nao fica como referencia ao produto: reajuste no cardapio
        nao pode reescrever o historico.
        """
        produto = repositorio.buscar_produto(db, "margherita")
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert pedido.itens[0].preco_unitario == produto.preco

    def test_guarda_a_observacao(self, db, ana):
        pedido = repositorio.salvar_pedido(
            db, ana.id, [{"produto": "margherita", "quantidade": 1, "observacao": "bem assada"}]
        )
        assert pedido.itens[0].observacao == "bem assada"

    def test_sem_endereco_usa_o_do_cadastro(self, db, ana):
        # o Sr. Antonio das personas nao quer ditar o endereco toda vez
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert pedido.endereco_entrega == ana.endereco

    def test_nasce_aberto(self, db, ana):
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert pedido.status == "aberto"

    def test_aceita_quantidade_em_texto(self, db, ana):
        # o modelo de linguagem devolve "3" com frequencia
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": "3"}])
        assert pedido.itens[0].quantidade == 3


class TestValidacaoContraOCardapio:
    def test_produto_inventado_nao_grava(self, db, ana):
        """RIA04: o modelo alucinou um produto. nada pode ir para o banco."""
        antes = quantos_pedidos(db)
        with pytest.raises(ValueError, match="nao existe no cardapio"):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "pizza de unicornio", "quantidade": 1}])
        assert quantos_pedidos(db) == antes

    def test_produto_desativado_nao_grava(self, db, ana):
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "escarola", "quantidade": 1}])

    def test_produto_ambiguo_vira_pergunta_e_nao_escolha(self, db, ana):
        with pytest.raises(ValueError, match="ambiguo"):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "pizza", "quantidade": 1}])

    def test_o_erro_lista_as_opcoes_para_o_atendente_perguntar(self, db, ana):
        with pytest.raises(ValueError) as erro:
            repositorio.salvar_pedido(db, ana.id, [{"produto": "borda", "quantidade": 1}])
        assert "Catupiry" in str(erro.value) and "Cheddar" in str(erro.value)


class TestQuantidade:
    def test_zero_nao_passa(self, db, ana):
        with pytest.raises(ValueError, match="maior que zero"):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 0}])

    def test_negativa_nao_passa(self, db, ana):
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": -2}])

    def test_quebrada_nao_e_truncada_em_silencio(self, db, ana):
        """
        "uma pizza e meia" vira 1.5. cortar para 1 cobraria a menos sem avisar ninguem:
        melhor devolver a duvida para o cliente.
        """
        with pytest.raises(ValueError, match="quebrada"):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1.5}])

    def test_inteiro_disfarcado_de_float_passa(self, db, ana):
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 2.0}])
        assert pedido.itens[0].quantidade == 2

    def test_texto_que_nao_e_numero_nao_passa(self, db, ana):
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": "duas"}])


class TestPedidoInvalido:
    def test_lista_vazia_nao_grava(self, db, ana):
        with pytest.raises(ValueError, match="sem nenhum item"):
            repositorio.salvar_pedido(db, ana.id, [])

    def test_cliente_inexistente_nao_grava(self, db):
        with pytest.raises(ValueError, match="nao existe"):
            repositorio.salvar_pedido(db, 999999, [{"produto": "margherita", "quantidade": 1}])

    def test_um_item_ruim_derruba_o_pedido_inteiro(self, db, ana):
        """ACID: ou grava tudo, ou nao grava nada. nao existe pedido pela metade."""
        antes = quantos_pedidos(db)
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(
                db, ana.id,
                [
                    {"produto": "margherita", "quantidade": 1},
                    {"produto": "pizza de unicornio", "quantidade": 1},
                ],
            )
        assert quantos_pedidos(db) == antes

    def test_a_sessao_sobrevive_ao_erro(self, db, ana):
        with pytest.raises(ValueError):
            repositorio.salvar_pedido(db, ana.id, [])
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert pedido.id is not None


class TestDinheiro:
    def test_total_e_decimal_e_nao_float(self, db, ana):
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 3}])
        assert isinstance(pedido.total, Decimal)

    def test_total_com_duas_casas(self, db, ana):
        pedido = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 3}])
        assert pedido.total == pedido.total.quantize(Decimal("0.01"))
