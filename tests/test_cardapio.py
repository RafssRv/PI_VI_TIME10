"""
consulta ao cardapio a partir do que o cliente falou (RF07), e a regra de ambiguidade
que sustenta o RIA04.
"""

from decimal import Decimal

import pytest

import repositorio
import seed

ATIVOS = [linha for linha in seed.CARDAPIO if linha[4]]


class TestListagem:
    def test_lista_so_o_que_esta_ativo(self, db):
        nomes = [produto.nome for produto in repositorio.listar_cardapio(db)]
        assert "Pizza de Escarola com Bacon" not in nomes  # o desativado do seed
        assert len(nomes) == len(ATIVOS)

    def test_pergunta_no_plural_funciona(self, db):
        # "quais bebidas voces tem?" chega como "bebidas", mas a categoria e "bebida"
        bebidas = repositorio.listar_cardapio(db, "bebidas")
        assert len(bebidas) == len([linha for linha in ATIVOS if linha[2] == "bebida"])
        assert all(produto.categoria == "bebida" for produto in bebidas)

    def test_pergunta_no_singular_funciona_igual(self, db):
        assert len(repositorio.listar_cardapio(db, "bebida")) == len(repositorio.listar_cardapio(db, "bebidas"))

    def test_categoria_composta(self, db):
        assert len(repositorio.listar_cardapio(db, "pizzas")) == len(
            [linha for linha in ATIVOS if linha[2].startswith("pizza")])


class TestBuscaPorNomeFalado:
    def test_acha_pelo_pedaco_do_nome(self, db):
        assert repositorio.buscar_produto(db, "margherita").nome == "Pizza Margherita"

    def test_ignora_hifen_e_acento(self, db):
        # a transcricao nao devolve hifen: "coca cola" tem que achar "Coca-Cola"
        assert repositorio.buscar_produto(db, "coca cola").nome == "Coca-Cola"

    def test_acha_com_a_frase_inteira(self, db):
        achado = repositorio.buscar_produto(db, "queria uma pizza de calabresa")
        assert achado.nome == "Pizza de Calabresa"

    def test_nao_acha_produto_inexistente(self, db):
        assert repositorio.buscar_produto(db, "pizza de unicornio") is None

    def test_nao_acha_produto_desativado(self, db):
        # RIA04: item fora do cardapio nao pode entrar no pedido por nenhuma via
        assert repositorio.buscar_produto(db, "escarola") is None


class TestAmbiguidade:
    def test_termo_generico_nao_escolhe_sozinho(self, db):
        """
        o cliente disse so "pizza". escolher um sabor aqui seria entregar o que ele nao
        pediu, calado. entao buscar_produto devolve None e quem chama pergunta.
        """
        assert repositorio.buscar_produto(db, "pizza") is None

    def test_mas_devolve_todos_os_candidatos_para_perguntar(self, db):
        candidatos = repositorio.buscar_produtos(db, "pizza")
        assert len(candidatos) == len([linha for linha in ATIVOS if linha[0].startswith("Pizza")])

    def test_borda_tambem_e_ambigua(self, db):
        assert repositorio.buscar_produto(db, "borda") is None
        assert len(repositorio.buscar_produtos(db, "borda")) == 2

    def test_nome_exato_ganha_de_qualquer_duvida(self, db):
        # "Pizza de Mussarela" esta contido em nada mais, mas o exato tem que vencer sempre
        assert repositorio.buscar_produto(db, "Pizza de Mussarela").nome == "Pizza de Mussarela"

    def test_termo_vazio_nao_devolve_o_cardapio_inteiro(self, db):
        assert repositorio.buscar_produtos(db, "") == []
        assert repositorio.buscar_produtos(db, None) == []


class TestCardapioPopulado:
    def test_tem_os_sabores_mais_pedidos(self, db):
        nomes = {produto.nome for produto in repositorio.listar_cardapio(db, "pizza salgada")}
        for sabor in ("Pizza de Calabresa", "Pizza Margherita", "Pizza Portuguesa", "Pizza de Pepperoni",
                      "Pizza de Frango com Catupiry", "Pizza Quatro Queijos", "Pizza Napolitana", "Pizza de Atum"):
            assert sabor in nomes
        assert len(nomes) >= 20

    def test_tem_agua_suco_e_refrigerante(self, db):
        nomes = {produto.nome for produto in repositorio.listar_cardapio(db, "bebida")}
        assert {"Água Mineral 500ml", "Água com Gás 500ml", "Suco de Laranja 1 Litro",
                "Coca-Cola", "Guaraná"} <= nomes

    @pytest.mark.parametrize("falado", [
        "napolitana", "toscana", "baiana", "atum", "bacon", "milho", "brocolis", "palmito", "champignon",
        "vegetariana", "caipira", "lombo", "rucula", "carne seca", "camarao", "banana", "prestigio",
        "fanta", "sprite", "agua com gas",
    ])
    def test_cada_sabor_novo_tem_um_nome_so_dele(self, db, falado):
        # se duas linhas do cardapio casassem, o atendente teria que perguntar qual eh
        assert repositorio.buscar_produto(db, falado) is not None

    def test_nomes_do_cardapio_nao_se_repetem(self):
        nomes = [linha[0] for linha in seed.CARDAPIO]
        assert len(nomes) == len(set(nomes))


class TestTamanhos:
    def test_tres_tamanhos_do_menor_pro_maior(self, db):
        tamanhos = repositorio.listar_tamanhos(db, "pizza")
        assert [t.nome for t in tamanhos] == ["pequena", "média", "grande"]
        assert [t.fatias for t in tamanhos] == [4, 6, 8]

    def test_refrigerante_tem_lata_600_e_2_litros(self, db):
        tamanhos = repositorio.listar_tamanhos(db, "refrigerante")
        assert [t.nome for t in tamanhos] == ["Lata", "600 ml", "2 Litros"]
        coca = repositorio.buscar_produto(db, "coca cola")
        assert [repositorio.preco_no_tamanho(coca, t) for t in tamanhos] == [
            Decimal("6.00"), Decimal("8.00"), Decimal("14.90")]

    def test_quem_tem_tamanho(self, db):
        assert repositorio.grupo_tamanho(repositorio.buscar_produto(db, "calabresa")) == "pizza"
        assert repositorio.grupo_tamanho(repositorio.buscar_produto(db, "guarana")) == "refrigerante"
        assert repositorio.grupo_tamanho(repositorio.buscar_produto(db, "agua mineral")) is None
        assert repositorio.grupo_tamanho(repositorio.buscar_produto(db, "suco de laranja")) is None

    def test_preco_do_cardapio_eh_o_da_grande(self, db):
        calabresa = repositorio.buscar_produto(db, "calabresa")
        tamanhos = {t.nome: t for t in repositorio.listar_tamanhos(db, "pizza")}
        assert repositorio.preco_no_tamanho(calabresa, tamanhos["grande"]) == Decimal("64.90")
        assert repositorio.preco_no_tamanho(calabresa, tamanhos["média"]) == Decimal("49.90")
        assert repositorio.preco_no_tamanho(calabresa, tamanhos["pequena"]) == Decimal("39.90")

    def test_toda_pizza_fica_com_preco_positivo_no_menor_tamanho(self, db):
        pequena = repositorio.listar_tamanhos(db, "pizza")[0]
        for produto in repositorio.listar_cardapio(db, "pizza"):
            assert repositorio.preco_no_tamanho(produto, pequena) > 0

    def test_so_pizza_tem_tamanho(self, db):
        assert repositorio.eh_pizza(repositorio.buscar_produto(db, "calabresa"))
        assert repositorio.eh_pizza(repositorio.buscar_produto(db, "brigadeiro"))
        assert not repositorio.eh_pizza(repositorio.buscar_produto(db, "coca cola"))
        assert not repositorio.eh_pizza(repositorio.buscar_produto(db, "borda de cheddar"))

    def test_banco_recusa_tamanho_repetido(self, db):
        from sqlalchemy.exc import IntegrityError
        from models import Tamanho

        db.add(Tamanho(nome="grande", fatias=8, desconto=Decimal("0")))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_banco_recusa_desconto_negativo(self, db):
        from sqlalchemy.exc import IntegrityError
        from models import Tamanho

        db.add(Tamanho(nome="gigante", fatias=12, desconto=Decimal("-10")))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_completar_banco_antigo_nao_duplica_nada(db):
    # o banco de teste ja tem tudo: completar de novo nao pode criar linha repetida
    assert seed.completar(db) == (0, 0)
