"""
consulta ao cardapio a partir do que o cliente falou (RF07), e a regra de ambiguidade
que sustenta o RIA04.
"""

import repositorio


class TestListagem:
    def test_lista_so_o_que_esta_ativo(self, db):
        nomes = [produto.nome for produto in repositorio.listar_cardapio(db)]
        assert "Pizza de Escarola com Bacon" not in nomes  # o desativado do seed
        assert len(nomes) == 18

    def test_pergunta_no_plural_funciona(self, db):
        # "quais bebidas voces tem?" chega como "bebidas", mas a categoria e "bebida"
        bebidas = repositorio.listar_cardapio(db, "bebidas")
        assert len(bebidas) == 4
        assert all(produto.categoria == "bebida" for produto in bebidas)

    def test_pergunta_no_singular_funciona_igual(self, db):
        assert len(repositorio.listar_cardapio(db, "bebida")) == 4

    def test_categoria_composta(self, db):
        assert len(repositorio.listar_cardapio(db, "pizzas")) == 10


class TestBuscaPorNomeFalado:
    def test_acha_pelo_pedaco_do_nome(self, db):
        assert repositorio.buscar_produto(db, "margherita").nome == "Pizza Margherita"

    def test_ignora_hifen_e_acento(self, db):
        # a transcricao nao devolve hifen: "coca cola" tem que achar "Coca-Cola 2 Litros"
        assert repositorio.buscar_produto(db, "coca cola").nome == "Coca-Cola 2 Litros"

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
        assert len(candidatos) == 10

    def test_borda_tambem_e_ambigua(self, db):
        assert repositorio.buscar_produto(db, "borda") is None
        assert len(repositorio.buscar_produtos(db, "borda")) == 2

    def test_nome_exato_ganha_de_qualquer_duvida(self, db):
        # "Pizza de Mussarela" esta contido em nada mais, mas o exato tem que vencer sempre
        assert repositorio.buscar_produto(db, "Pizza de Mussarela").nome == "Pizza de Mussarela"

    def test_termo_vazio_nao_devolve_o_cardapio_inteiro(self, db):
        assert repositorio.buscar_produtos(db, "") == []
        assert repositorio.buscar_produtos(db, None) == []
