"""
historico do cliente e recomendacao (RF05 e RF08), incluindo o caminho do cliente novo,
que nao tem historico nenhum.
"""

import repositorio


class TestHistorico:
    def test_traz_os_pedidos_do_cliente(self, db, ana):
        historico = repositorio.historico_cliente(db, ana.id)
        assert historico
        assert all(pedido.cliente_id == ana.id for pedido in historico)

    def test_respeita_o_limite(self, db, ana):
        assert len(repositorio.historico_cliente(db, ana.id, limite=2)) == 2

    def test_vem_do_mais_recente_para_o_mais_antigo(self, db, ana):
        historico = repositorio.historico_cliente(db, ana.id, limite=5)
        datas = [pedido.criado_em for pedido in historico]
        assert datas == sorted(datas, reverse=True)

    def test_os_itens_vem_junto(self, db, ana):
        # carregados na mesma consulta: uma conversa nao pode esperar n+1 idas ao banco
        historico = repositorio.historico_cliente(db, ana.id, limite=3)
        assert all(len(pedido.itens) > 0 for pedido in historico)

    def test_cliente_novo_nao_tem_historico(self, db):
        novo = repositorio.criar_cliente(db, "Joao da Silva", "11122233396")
        assert repositorio.historico_cliente(db, novo.id) == []


class TestRecomendacao:
    def test_sugere_o_que_o_cliente_mais_pede(self, db, ana):
        favoritos = repositorio.itens_mais_pedidos_do_cliente(db, ana.id)
        assert favoritos
        produto, quantidade = favoritos[0]
        assert quantidade > 0
        assert produto.ativo

    def test_vem_ordenado_do_mais_pedido_para_o_menos(self, db, ana):
        favoritos = repositorio.itens_mais_pedidos_do_cliente(db, ana.id)
        quantidades = [quantidade for _, quantidade in favoritos]
        assert quantidades == sorted(quantidades, reverse=True)

    def test_respeita_o_limite(self, db, ana):
        assert len(repositorio.itens_mais_pedidos_do_cliente(db, ana.id, limite=2)) == 2

    def test_cliente_novo_nao_tem_favorito(self, db):
        novo = repositorio.criar_cliente(db, "Joao da Silva", "11122233396")
        assert repositorio.itens_mais_pedidos_do_cliente(db, novo.id) == []

    def test_mas_a_casa_sempre_tem_o_que_sugerir(self, db):
        """RF08: o fallback do cliente novo sao os campeoes de venda do estabelecimento."""
        campeoes = repositorio.itens_mais_pedidos_da_casa(db)
        assert len(campeoes) == 3
        assert all(quantidade > 0 for _, quantidade in campeoes)

    def test_a_casa_nao_recomenda_produto_desativado(self, db):
        campeoes = repositorio.itens_mais_pedidos_da_casa(db, limite=20)
        assert all(produto.ativo for produto, _ in campeoes)
