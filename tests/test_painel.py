"""Dashboard do administrador: agregação pura, consultas do repositório e a rota."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import painel

AGORA = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc).astimezone()


def pedido(id, dias_atras, total, cliente_id=1, nome="Ana Beatriz Moraes", forma="pix", status="concluido"):
    return SimpleNamespace(id=id, criado_em=AGORA - timedelta(days=dias_atras), total=Decimal(total),
                           forma_pagamento=forma, status=status, cliente_id=cliente_id, nome=nome)


def item(pedido_id, nome, quantidade, preco, categoria="pizza salgada"):
    return SimpleNamespace(pedido_id=pedido_id, nome=nome, categoria=categoria,
                           quantidade=quantidade, preco_unitario=Decimal(preco))


def montar(pedidos, itens, primeiras=None, cardapio=(), dias=7, anterior=None):
    desde, _ = painel.periodo(dias, AGORA)
    return painel.montar_painel(pedidos, itens, primeiras or {}, list(cardapio), dias, desde, AGORA, anterior)


class TestPeriodo:
    def test_sete_dias_comeca_a_meia_noite_de_seis_dias_atras(self):
        desde, anterior = painel.periodo(7, AGORA)
        assert (desde.hour, desde.minute) == (0, 0)
        assert AGORA.date() - desde.date() == timedelta(days=6)
        assert desde - anterior == timedelta(days=7)

    def test_tudo_nao_tem_inicio_nem_comparacao(self):
        assert painel.periodo(0, AGORA) == (None, None)

    def test_recusa_periodo_fora_da_lista(self):
        with pytest.raises(ValueError):
            painel.periodo(5, AGORA)


class TestResumo:
    def test_soma_pedidos_faturamento_e_ticket(self):
        dados = montar([pedido(1, 0, "50.00"), pedido(2, 1, "25.00", cliente_id=2, nome="Carlos")], [])
        r = dados["resumo"]
        assert (r["pedidos"], r["faturamento"], r["ticket_medio"], r["clientes"]) == (2, "75.00", "37.50", 2)

    def test_periodo_sem_pedido_nao_divide_por_zero(self):
        r = montar([], [])["resumo"]
        assert (r["pedidos"], r["faturamento"], r["ticket_medio"]) == (0, "0.00", "0.00")
        assert all(dia["pedidos"] == 0 for dia in montar([], [])["por_dia"])

    def test_cliente_novo_eh_quem_comprou_pela_primeira_vez_no_periodo(self):
        pedidos = [pedido(1, 0, "10", cliente_id=1), pedido(2, 0, "10", cliente_id=2)]
        primeiras = {1: AGORA - timedelta(days=100), 2: AGORA - timedelta(days=1)}
        assert montar(pedidos, [], primeiras)["resumo"]["clientes_novos"] == 1

    def test_variacao_contra_o_periodo_anterior(self):
        r = montar([pedido(1, 0, "150.00")], [], anterior=(2, Decimal("100.00")))["resumo"]
        assert r["variacao_faturamento"] == 50.0
        assert r["variacao_pedidos"] == -50.0

    def test_sem_base_anterior_nao_inventa_porcentagem(self):
        r = montar([pedido(1, 0, "10")], [], anterior=(0, Decimal("0")))["resumo"]
        assert r["variacao_pedidos"] is None and r["variacao_faturamento"] is None


class TestSeries:
    def test_dias_sem_venda_entram_zerados(self):
        dados = montar([pedido(1, 0, "10"), pedido(2, 3, "20")], [])
        assert len(dados["por_dia"]) == 7
        assert [d["pedidos"] for d in dados["por_dia"]] == [0, 0, 0, 1, 0, 0, 1]
        assert dados["por_dia"][-1]["faturamento"] == "10.00"

    def test_vinte_e_quatro_horas(self):
        dados = montar([pedido(1, 0, "10")], [])
        assert len(dados["por_hora"]) == 24
        assert dados["por_hora"][AGORA.hour]["pedidos"] == 1

    def test_tudo_comeca_no_primeiro_pedido(self):
        dados = montar([pedido(1, 10, "10")], [], dias=0)
        assert len(dados["por_dia"]) == 11


class TestProdutos:
    def test_mais_vendidos_por_quantidade_com_o_preco_da_venda(self):
        itens = [item(1, "Pizza de Calabresa", 3, "64.90"), item(2, "Coca-Cola 2 Litros", 1, "14.90", "bebida"),
                 item(2, "Pizza de Calabresa", 1, "60.00")]
        dados = montar([pedido(1, 0, "194.70"), pedido(2, 0, "74.90")], itens)
        primeiro = dados["mais_vendidos"][0]
        assert (primeiro["produto"], primeiro["quantidade"], primeiro["faturamento"]) == ("Pizza de Calabresa", 4, "254.70")
        assert dados["resumo"]["itens_vendidos"] == 5
        assert dados["por_categoria"][0]["categoria"] == "pizza salgada"

    def test_limita_a_cinco_produtos(self):
        itens = [item(1, "Produto {}".format(n), 1, "1") for n in range(8)]
        assert len(montar([pedido(1, 0, "8")], itens)["mais_vendidos"]) == 5

    def test_pagamento_sem_forma_vira_nao_informado(self):
        dados = montar([pedido(1, 0, "10", forma=None), pedido(2, 0, "10"), pedido(3, 0, "10")], [])
        assert [(p["forma"], p["pedidos"]) for p in dados["pagamentos"]] == [("pix", 2), ("nao_informado", 1)]


class TestPrivacidade:
    def test_ultimos_pedidos_so_mostram_o_primeiro_nome(self):
        dados = montar([pedido(1, 0, "10")], [item(1, "Pizza", 2, "5")])
        ultimo = dados["ultimos_pedidos"][0]
        assert ultimo["cliente"] == "Ana"
        assert ultimo["itens"] == 2
        assert set(ultimo) == {"id", "criado_em", "cliente", "itens", "total", "forma_pagamento", "status"}

    def test_ultimos_vem_do_mais_recente(self):
        dados = montar([pedido(1, 3, "10"), pedido(2, 0, "10")], [])
        assert [p["id"] for p in dados["ultimos_pedidos"]] == [2, 1]

    def test_cardapio_lista_os_indisponiveis(self):
        cardapio = [SimpleNamespace(nome="Pizza A", ativo=True), SimpleNamespace(nome="Pizza B", ativo=False)]
        assert montar([], [], cardapio=cardapio)["cardapio"] == {"ativos": 1, "indisponiveis": ["Pizza B"]}


class TestRepositorio:
    def test_le_todos_os_pedidos_do_seed(self, db):
        import repositorio
        import seed
        from models import Pedido

        pedidos, itens = repositorio.dados_do_painel(db)
        assert len(pedidos) == sum(quantos for _, quantos, _ in seed.PERFIS) == db.query(Pedido).count()
        assert itens and all(i.quantidade > 0 for i in itens)
        # nada de dado sensivel nas linhas do painel
        assert not hasattr(pedidos[0], "cpf_hash") and not hasattr(pedidos[0], "telefone")

    def test_totais_batem_com_as_linhas(self, db):
        import repositorio

        pedidos, _ = repositorio.dados_do_painel(db)
        quantidade, faturamento = repositorio.totais_do_periodo(db)
        assert quantidade == len(pedidos)
        assert faturamento == sum(Decimal(str(p.total)) for p in pedidos)

    def test_pedido_cancelado_nao_conta(self, db, ana):
        import repositorio

        antes = repositorio.totais_do_periodo(db)
        pedido_novo = repositorio.salvar_pedido(db, ana.id, [{"produto": "margherita", "quantidade": 1}])
        assert repositorio.totais_do_periodo(db)[0] == antes[0] + 1
        pedido_novo.status = "cancelado"
        db.commit()
        assert repositorio.totais_do_periodo(db) == antes

    def test_primeira_compra_por_cliente(self, db, ana):
        import repositorio

        primeiras = repositorio.primeiras_compras(db, {ana.id})
        assert set(primeiras) == {ana.id}
        assert repositorio.primeiras_compras(db, set()) == {}


class TestRota:
    def test_painel_responde_em_desenvolvimento(self, db, monkeypatch, tmp_path):
        from test_rotas import requisitar
        import importlib.util
        import config
        import main

        monkeypatch.setattr(config, "AMBIENTE", "dev")
        spec = importlib.util.spec_from_file_location("aplicativo_painel", main.__file__)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)

        status, corpo = requisitar(modulo.app, "/api/admin/painel")
        assert status == 200
        dados = json.loads(corpo)
        assert {"resumo", "por_dia", "mais_vendidos", "pagamentos", "ultimos_pedidos"} <= set(dados)

        assert requisitar(modulo.app, "/admin/")[0] == 200
