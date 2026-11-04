"""Números do painel do administrador.

Recebe linhas já lidas pelo repositório e devolve o JSON da dashboard. Não acessa o banco,
então dá pra testar com objetos simples. Dinheiro sai como string com duas casas, igual ao
resto do protocolo da tela.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

# 0 = desde o primeiro pedido
PERIODOS = (7, 30, 90, 0)
LIMITE_PRODUTOS = 5
LIMITE_ULTIMOS = 8
CENTAVO = Decimal("0.01")


def _dinheiro(valor):
    return format(Decimal(str(valor)).quantize(CENTAVO), ".2f")


def _local(momento):
    # mesmo fuso da maquina do servidor, como o historico falado pelo atendente
    return momento.astimezone()


def periodo(dias, agora):
    """
    (inicio do periodo, inicio do periodo anterior). "7 dias" eh hoje e os 6 dias antes,
    contados da meia-noite. dias=0 nao tem inicio nem comparacao.
    """
    if dias not in PERIODOS:
        raise ValueError("periodo invalido")
    if dias == 0:
        return None, None
    meia_noite = _local(agora).replace(hour=0, minute=0, second=0, microsecond=0)
    desde = meia_noite - timedelta(days=dias - 1)
    return desde, desde - timedelta(days=dias)


def _variacao(atual, anterior):
    # sem base de comparacao nao tem porcentagem: a tela mostra "sem comparação"
    if anterior is None or not anterior:
        return None
    return round(float((Decimal(str(atual)) - Decimal(str(anterior))) / Decimal(str(anterior)) * 100), 1)


def _primeiro_nome(nome):
    partes = (nome or "").split()
    return partes[0] if partes else "Cliente"


def montar_painel(pedidos, itens, primeiras, cardapio, dias, desde, agora, anterior=None):
    """
    pedidos: linhas com id, criado_em, total, forma_pagamento, status, cliente_id, nome
    itens: linhas com pedido_id, nome, categoria, quantidade, preco_unitario
    primeiras: {cliente_id: data do primeiro pedido}
    cardapio: produtos (nome, ativo), ativos e inativos
    anterior: (pedidos, faturamento) do periodo anterior, ou None
    """
    quantidade = len(pedidos)
    faturamento = sum((Decimal(str(p.total)) for p in pedidos), Decimal("0"))
    ticket = (faturamento / quantidade).quantize(CENTAVO) if quantidade else Decimal("0")
    clientes = {p.cliente_id for p in pedidos}
    novos = sum(1 for c in clientes if desde is None or (primeiras.get(c) and primeiras[c] >= desde))

    # --- por dia, com os dias sem venda zerados pro grafico nao pular datas ---
    por_dia = defaultdict(lambda: [0, Decimal("0")])
    for p in pedidos:
        dia = _local(p.criado_em).date()
        por_dia[dia][0] += 1
        por_dia[dia][1] += Decimal(str(p.total))
    hoje = _local(agora).date()
    if desde is not None:
        primeiro_dia = _local(desde).date()
    else:
        primeiro_dia = min(por_dia) if por_dia else hoje
    serie = []
    dia = primeiro_dia
    while dia <= hoje:
        contagem, valor = por_dia.get(dia, (0, Decimal("0")))
        serie.append({"data": dia.isoformat(), "pedidos": contagem, "faturamento": _dinheiro(valor)})
        dia += timedelta(days=1)

    por_hora = [0] * 24
    for p in pedidos:
        por_hora[_local(p.criado_em).hour] += 1

    # --- produtos e categorias, pelo preco gravado no item (o da venda, nao o de hoje) ---
    produtos = defaultdict(lambda: {"quantidade": 0, "faturamento": Decimal("0"), "categoria": ""})
    categorias = defaultdict(lambda: {"quantidade": 0, "faturamento": Decimal("0")})
    itens_por_pedido = defaultdict(int)
    for item in itens:
        valor = Decimal(str(item.preco_unitario)) * item.quantidade
        produtos[item.nome]["quantidade"] += item.quantidade
        produtos[item.nome]["faturamento"] += valor
        produtos[item.nome]["categoria"] = item.categoria
        categorias[item.categoria]["quantidade"] += item.quantidade
        categorias[item.categoria]["faturamento"] += valor
        itens_por_pedido[item.pedido_id] += item.quantidade

    mais_vendidos = sorted(produtos.items(), key=lambda par: (-par[1]["quantidade"], -par[1]["faturamento"], par[0]))
    por_categoria = sorted(categorias.items(), key=lambda par: (-par[1]["faturamento"], par[0]))

    pagamentos = defaultdict(lambda: [0, Decimal("0")])
    for p in pedidos:
        forma = p.forma_pagamento or "nao_informado"
        pagamentos[forma][0] += 1
        pagamentos[forma][1] += Decimal(str(p.total))

    ultimos = sorted(pedidos, key=lambda p: (p.criado_em, p.id), reverse=True)[:LIMITE_ULTIMOS]

    pedidos_antes, faturamento_antes = anterior if anterior else (None, None)

    return {
        "periodo": {
            "dias": dias,
            "inicio": desde.isoformat() if desde else None,
            "gerado_em": _local(agora).isoformat(),
        },
        "resumo": {
            "pedidos": quantidade,
            "faturamento": _dinheiro(faturamento),
            "ticket_medio": _dinheiro(ticket),
            "clientes": len(clientes),
            "clientes_novos": novos,
            "itens_vendidos": sum(i.quantidade for i in itens),
            "variacao_pedidos": _variacao(quantidade, pedidos_antes),
            "variacao_faturamento": _variacao(faturamento, faturamento_antes),
        },
        "por_dia": serie,
        "por_hora": [{"hora": h, "pedidos": n} for h, n in enumerate(por_hora)],
        "mais_vendidos": [
            {"produto": nome, "categoria": d["categoria"], "quantidade": d["quantidade"],
             "faturamento": _dinheiro(d["faturamento"])}
            for nome, d in mais_vendidos[:LIMITE_PRODUTOS]
        ],
        "por_categoria": [
            {"categoria": nome, "quantidade": d["quantidade"], "faturamento": _dinheiro(d["faturamento"])}
            for nome, d in por_categoria
        ],
        "pagamentos": [
            {"forma": forma, "pedidos": n, "faturamento": _dinheiro(valor)}
            for forma, (n, valor) in sorted(pagamentos.items(), key=lambda par: (-par[1][0], par[0]))
        ],
        # so o primeiro nome: a dashboard fica aberta na tela e nao precisa de dado pessoal
        "ultimos_pedidos": [
            {"id": p.id, "criado_em": _local(p.criado_em).isoformat(), "cliente": _primeiro_nome(p.nome),
             "itens": itens_por_pedido.get(p.id, 0), "total": _dinheiro(p.total),
             "forma_pagamento": p.forma_pagamento, "status": p.status}
            for p in ultimos
        ],
        "cardapio": {
            "ativos": sum(1 for p in cardapio if p.ativo),
            "indisponiveis": sorted(p.nome for p in cardapio if not p.ativo),
        },
    }
