# esse modulo eh a unica porta de entrada pro banco: rota, websocket e o codigo da ia chamam
# as funcoes daqui. ninguem consulta o banco por fora, senao daqui a pouco tem cpf em texto
# puro numa query e pedido gravado sem validar o cardapio (ria04).
# toda funcao recebe a Session (db) pronta de fora, quem abre e fecha eh o get_db do database.py.

import re
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from models import Cliente, ItemPedido, Pedido, Produto, Tamanho
from seguranca import hashear_cpf
from interpretacao import _normalizar

# a coluna pedido.forma_pagamento eh VARCHAR(20) e o seed so usa esses quatro valores.
# o que o modelo extrair da fala tem q cair num deles, senao nao grava
FORMAS_PAGAMENTO = ("pix", "dinheiro", "cartao_credito", "cartao_debito")

# ninguem fala "cartao_credito" no telefone, fala "no cartao de credito", "credito",
# "vou pagar em dinheiro, troco pra cem". esses sao os sinais que a gente procura na frase:
# palavra encontrada -> forma canonica
SINAIS_DE_PAGAMENTO = {
    "pix": "pix",
    # como o whisper costuma escrever "pix"
    "pics": "pix",
    "picks": "pix",
    "piques": "pix",
    "pixe": "pix",
    "dinheiro": "dinheiro",
    "especie": "dinheiro",
    "vivo": "dinheiro",
    "credito": "cartao_credito",
    "debito": "cartao_debito",
}

# "cartao" e "maquininha" sozinhos nao dizem se eh credito ou debito: pergunta, nao chuta
SINAIS_AMBIGUOS = ("cartao", "maquininha", "cartao de credito ou debito")


def _so_digitos(texto):
    # telefone chega da fala cheio de parentese, traco e palavra solta ("(19) 99812-4477 whatsapp")
    if not texto:
        return None
    digitos = re.sub(r"\D", "", str(texto))
    return digitos or None


def interpretar_pagamento(forma_pagamento):
    """
    traduz a forma de pagamento como o cliente falou para uma das FORMAS_PAGAMENTO.
    levanta ValueError quando nao da pra ter certeza, pq gravar pagamento errado eh pior
    que perguntar de novo.
    """
    texto = _normalizar(forma_pagamento)
    if not texto:
        raise ValueError("forma de pagamento vazia, pergunte ao cliente como ele vai pagar.")

    # ja veio canonico ("cartao_credito") ou quase ("cartao credito")
    if texto.replace(" ", "_") in FORMAS_PAGAMENTO:
        return texto.replace(" ", "_")

    palavras = texto.split()
    achados = {SINAIS_DE_PAGAMENTO[p] for p in palavras if p in SINAIS_DE_PAGAMENTO}

    if len(achados) == 1:
        return achados.pop()

    if len(achados) > 1:
        # "dinheiro ou cartao de credito": o cliente ainda nao decidiu
        raise ValueError(
            "o cliente citou mais de uma forma de pagamento ({}), confirme qual delas.".format(
                ", ".join(sorted(achados))
            )
        )

    if any(sinal in texto for sinal in SINAIS_AMBIGUOS):
        raise ValueError("cartao no credito ou no debito? pergunte ao cliente.")

    raise ValueError(
        "forma de pagamento {!r} nao reconhecida, confirme com o cliente: {}.".format(
            forma_pagamento, ", ".join(FORMAS_PAGAMENTO)
        )
    )


def buscar_cliente_por_cpf(db, cpf):
    """RF03: identifica o cliente pelo cpf. levanta ValueError se o cpf nao for valido."""
    cpf_hash = hashear_cpf(cpf)
    return db.query(Cliente).filter(Cliente.cpf_hash == cpf_hash).first()


def criar_cliente(db, nome, cpf, telefone=None, endereco=None):
    """RF04: cadastra o cliente no meio da conversa quando o cpf ainda nao existe no banco."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("nome do cliente esta vazio, pergunte o nome antes de cadastrar.")

    # nome eh VARCHAR(100) e telefone VARCHAR(20): se passar do tamanho o postgres so reclama
    # la no commit, com erro de driver. entao corta/valida aqui, antes de tocar no banco
    nome = nome[:100]
    telefone = _so_digitos(telefone)
    if telefone and len(telefone) > 20:
        raise ValueError(
            "telefone {!r} tem digito demais, confirme o numero com o cliente.".format(telefone)
        )

    cpf_hash = hashear_cpf(cpf)

    # confere antes so pra dar mensagem boa; o unique do banco continua sendo a garantia de verdade
    if db.query(Cliente).filter(Cliente.cpf_hash == cpf_hash).first():
        raise ValueError("ja existe cliente com esse cpf, use buscar_cliente_por_cpf em vez de cadastrar.")

    cliente = Cliente(nome=nome, cpf_hash=cpf_hash, telefone=telefone, endereco=endereco)
    db.add(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValueError("ja existe cliente com esse cpf.")
    except Exception:
        # qualquer outro erro tem q soltar a transacao tambem: sem o rollback a sessao fica
        # abortada e TODA query depois dela morre, o que no websocket derruba a conversa inteira
        db.rollback()
        raise

    db.refresh(cliente)
    return cliente


def listar_cardapio(db, categoria=None, apenas_ativos=True):
    """
    RF07: cardapio inteiro ou de uma categoria, pra responder duvida sobre produto e preco.
    a categoria vem da fala ("quais bebidas voces tem?"), entao compara pelo radical no
    singular: "bebidas" acha "bebida" e "pizzas" acha "pizza salgada" e "pizza doce".
    """
    consulta = db.query(Produto)
    if apenas_ativos:
        consulta = consulta.filter(Produto.ativo.is_(True))
    if categoria:
        radical = " ".join(palavra.rstrip("s") for palavra in _normalizar(categoria).split())
        if radical:
            consulta = consulta.filter(Produto.categoria.ilike("%" + radical + "%"))
    return consulta.order_by(Produto.categoria, Produto.nome).all()


def listar_tamanhos(db, grupo=None):
    """
    tamanhos de um grupo ("pizza" ou "refrigerante"), do menor pro maior. o preco do cardapio
    eh o do maior (pizza grande, refrigerante de 2 litros) e cada tamanho guarda o desconto.
    """
    consulta = db.query(Tamanho)
    if grupo:
        consulta = consulta.filter(Tamanho.grupo == grupo)
    return consulta.order_by(Tamanho.grupo, Tamanho.desconto.desc()).all()


def grupo_tamanho(produto):
    """qual grupo de tamanhos vale pro produto. agua, suco, sobremesa e borda tem um preco so."""
    grupo = getattr(produto, "grupo_tamanho", None)
    if grupo:
        return grupo
    # banco antigo, de antes do grupo: pizza continua tendo tamanho pela categoria
    return "pizza" if eh_pizza_pela_categoria(produto) else None


def eh_pizza_pela_categoria(produto):
    return _normalizar(getattr(produto, "categoria", "")).startswith("pizza")


def eh_pizza(produto):
    return grupo_tamanho(produto) == "pizza"


def preco_no_tamanho(produto, tamanho=None):
    """preco no tamanho pedido: o do cardapio (maior tamanho) menos o desconto do tamanho."""
    preco = Decimal(str(produto.preco))
    if tamanho is not None:
        preco -= Decimal(str(tamanho.desconto))
    return preco


def buscar_produtos(db, nome):
    """
    RF07/RIA04: todo produto ativo que bate com o pedaco de nome que veio da transcricao.
    devolve lista pq "pizza" casa com 10 sabores e quem decide qual eh o cliente, nao o codigo.
    """
    termo = _normalizar(nome)
    if not termo:
        return []

    # o cardapio tem poucas dezenas de linhas, entao traz tudo e compara ja normalizado dos dois
    # lados: assim "coca cola" acha "Coca-Cola 2 Litros" e "acai" acha "Açaí", o que o ilike do
    # postgres sozinho nao faz (ele nao ignora acento nem hifen)
    ativos = db.query(Produto).filter(Produto.ativo.is_(True)).order_by(Produto.nome).all()

    # nome exato ganha de tudo: "pizza de mussarela" nao pode virar duvida
    exatos = [p for p in ativos if _normalizar(p.nome) == termo]
    if exatos:
        return exatos

    # termo dentro do nome do cardapio: "margherita" -> "Pizza Margherita"
    contidos = [p for p in ativos if termo in _normalizar(p.nome)]
    if contidos:
        return contidos

    # caminho inverso, quando a fala inteira veio junto ("queria uma pizza de mussarela")
    return [p for p in ativos if _normalizar(p.nome) in termo]


def buscar_produto(db, nome):
    """
    RF07/RIA04: devolve o produto so quando nao tem duvida nenhuma (um unico candidato).
    se a fala casar com varios, devolve None de proposito: escolher um no desempate eh gravar
    pedido errado calado. quem precisa da lista pra perguntar ao cliente usa buscar_produtos.
    """
    candidatos = buscar_produtos(db, nome)
    if len(candidatos) == 1:
        return candidatos[0]
    return None


def historico_cliente(db, cliente_id, limite=5):
    """RF05: ultimos pedidos do cliente com os itens ja carregados, base da recomendacao."""
    return (
        db.query(Pedido)
        .filter(Pedido.cliente_id == cliente_id)
        # selectinload puxa os itens numa query so, senao vira n+1 (uma query por pedido)
        .options(
            selectinload(Pedido.itens).joinedload(ItemPedido.produto),
            selectinload(Pedido.itens).joinedload(ItemPedido.tamanho),
        )
        .order_by(Pedido.criado_em.desc(), Pedido.id.desc())
        .limit(limite)
        .all()
    )


def itens_mais_pedidos_do_cliente(db, cliente_id, limite=3, categoria=None):
    """RF08: o que esse cliente mais pediu, do mais pedido pro menos, pra sugerir o de sempre."""
    consulta = (
        db.query(Produto, func.sum(ItemPedido.quantidade))
        .join(ItemPedido, ItemPedido.produto_id == Produto.id)
        .join(Pedido, Pedido.id == ItemPedido.pedido_id)
        .filter(Pedido.cliente_id == cliente_id, Produto.ativo.is_(True))
    )
    if categoria:
        consulta = consulta.filter(Produto.categoria.ilike("%" + categoria + "%"))
    linhas = (
        consulta.group_by(Produto.id)
        .order_by(func.sum(ItemPedido.quantidade).desc(), Produto.nome)
        .limit(limite)
        .all()
    )
    return [(produto, int(quantidade)) for produto, quantidade in linhas]


def itens_mais_pedidos_da_casa(db, limite=3, categoria=None):
    """RF08: campeoes de venda da casa, fallback da recomendacao quando o cliente eh novo."""
    consulta = (
        db.query(Produto, func.sum(ItemPedido.quantidade))
        .join(ItemPedido, ItemPedido.produto_id == Produto.id)
        .filter(Produto.ativo.is_(True))
    )
    if categoria:
        consulta = consulta.filter(Produto.categoria.ilike("%" + categoria + "%"))
    linhas = (
        consulta.group_by(Produto.id)
        .order_by(func.sum(ItemPedido.quantidade).desc(), Produto.nome)
        .limit(limite)
        .all()
    )
    return [(produto, int(quantidade)) for produto, quantidade in linhas]


def salvar_pedido(db, cliente_id, itens, endereco_entrega=None, forma_pagamento=None, troco_para=None):
    """
    RF09/RF11 + RIA04: valida cada item contra o cardapio e grava pedido e itens numa transacao so.
    forma_pagamento pode vir None de proposito (pedido nasce 'aberto' e alguem fecha depois),
    mas se vier tem q ser uma das FORMAS_PAGAMENTO.
    """
    if not itens:
        raise ValueError("pedido sem nenhum item, confirme o pedido com o cliente antes de salvar.")

    # forma de pagamento tambem eh dado solto que o modelo extraiu da fala, entao passa pelo
    # mesmo crivo do produto: fora do vocabulario nao grava. a coluna eh VARCHAR(20) e
    # "cartao de credito na maquininha" estouraria la no commit, com o pedido inteiro ja montado
    if forma_pagamento is not None:
        forma_pagamento = interpretar_pagamento(forma_pagamento)

    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise ValueError(
            "cliente {} nao existe, identifique ou cadastre antes de salvar o pedido.".format(cliente_id)
        )

    # valida tudo primeiro e so depois toca no banco: erro de item nem chega a abrir transacao
    validados = []
    total = Decimal("0.00")
    tamanhos = {(t.grupo, _normalizar(t.nome)): t for t in listar_tamanhos(db)}

    for item in itens:
        nome_falado = item.get("produto")
        candidatos = buscar_produtos(db, nome_falado)
        # ria04: se o modelo inventou produto, o pedido inteiro para aqui e nada vai pro banco
        if not candidatos:
            raise ValueError(
                "produto {!r} nao existe no cardapio, confirme com o cliente.".format(nome_falado)
            )
        # ambiguo para tambem: "pizza" casa com 10 sabores, escolher um aqui eh entregar
        # Margherita pra quem so disse "quero uma pizza"
        if len(candidatos) > 1:
            raise ValueError(
                "produto {!r} esta ambiguo, pergunte ao cliente qual deles: {}.".format(
                    nome_falado, ", ".join(p.nome for p in candidatos)
                )
            )
        produto = candidatos[0]

        bruta = item.get("quantidade", 1)
        try:
            quantidade = int(bruta)
        except (TypeError, ValueError):
            raise ValueError(
                "quantidade invalida para {!r}: {!r}".format(produto.nome, bruta)
            )

        # "uma pizza e meia" vira 1.5 e o int() cortava pra 1 calado, cobrando a menos.
        # meia pizza nao existe no cardapio: melhor perguntar do que decidir pelo cliente
        if quantidade != bruta and not isinstance(bruta, str):
            raise ValueError(
                "quantidade de {!r} veio quebrada ({!r}), confirme quantas unidades o cliente quer.".format(
                    produto.nome, bruta
                )
            )

        if quantidade <= 0:
            raise ValueError("quantidade de {!r} precisa ser maior que zero.".format(produto.nome))

        # pizza ou refrigerante sem tamanho nao tem preco: cobrar o maior calado eh cobrar a mais
        falado = item.get("tamanho")
        grupo = grupo_tamanho(produto)
        tamanho = tamanhos.get((grupo, _normalizar(falado))) if falado and grupo else None
        if grupo:
            if not falado:
                raise ValueError("falta o tamanho de {!r}, pergunte ao cliente.".format(produto.nome))
            if tamanho is None:
                raise ValueError("tamanho {!r} nao existe para {!r}, as opcoes sao: {}.".format(
                    falado, produto.nome, ", ".join(t.nome for (g, _), t in tamanhos.items() if g == grupo)))
        elif falado:
            raise ValueError("{!r} tem tamanho unico.".format(produto.nome))

        # str() antes do Decimal pq se alguem trocar a coluna por float, Decimal(float) vira dizima
        preco_unitario = preco_no_tamanho(produto, tamanho)
        if preco_unitario <= 0:
            raise ValueError("o preco de {!r} ficou zerado, confira o cardapio.".format(produto.nome))
        if "preco_confirmado" in item and preco_unitario != item["preco_confirmado"]:
            raise ValueError("O preço mudou; apresente um novo resumo antes de salvar.")
        total += preco_unitario * quantidade
        validados.append((produto, quantidade, preco_unitario, item.get("observacao"), tamanho))

    # troco so existe pagando em dinheiro, e com uma nota maior que o total
    if troco_para is not None:
        troco_para = Decimal(str(troco_para)).quantize(Decimal("0.01"))
        if forma_pagamento != "dinheiro":
            raise ValueError("troco so vale para pagamento em dinheiro.")
        if troco_para <= total:
            raise ValueError("troco para {} nao cobre o total de {}.".format(troco_para, total))

    pedido = Pedido(
        cliente_id=cliente_id,
        endereco_entrega=endereco_entrega or cliente.endereco,
        forma_pagamento=forma_pagamento,
        troco_para=troco_para,
        total=total.quantize(Decimal("0.01")),
    )
    for produto, quantidade, preco_unitario, observacao, tamanho in validados:
        pedido.itens.append(
            ItemPedido(
                produto_id=produto.id,
                quantidade=quantidade,
                preco_unitario=preco_unitario,
                observacao=observacao,
                tamanho_id=tamanho.id if tamanho else None,
            )
        )

    db.add(pedido)
    try:
        db.commit()
    except Exception:
        # acid: se qualquer coisa estourar no commit, o rollback derruba pedido e itens juntos,
        # nao fica pedido pela metade no banco
        db.rollback()
        raise

    db.refresh(pedido)
    # carrega os itens agora, com a sessao ainda aberta, pq quem chamou vai ler isso depois
    list(pedido.itens)
    return pedido



# --- painel do administrador ---
# so le colunas que o painel mostra: cpf_hash, telefone e endereco nunca saem daqui

def _pedidos_validos(consulta, desde=None, ate=None):
    # pedido cancelado nao eh venda: fica fora do faturamento e das contagens
    consulta = consulta.filter(Pedido.status != "cancelado")
    if desde is not None:
        consulta = consulta.filter(Pedido.criado_em >= desde)
    if ate is not None:
        consulta = consulta.filter(Pedido.criado_em < ate)
    return consulta


def dados_do_painel(db, desde=None, ate=None):
    """pedidos do periodo e os itens deles, em duas consultas, para o painel agregar."""
    pedidos = _pedidos_validos(
        db.query(Pedido.id, Pedido.criado_em, Pedido.total, Pedido.forma_pagamento,
                 Pedido.status, Pedido.cliente_id, Cliente.nome)
        .join(Cliente, Cliente.id == Pedido.cliente_id),
        desde, ate,
    ).order_by(Pedido.criado_em, Pedido.id).all()

    itens = _pedidos_validos(
        db.query(ItemPedido.pedido_id, Produto.nome, Produto.categoria,
                 ItemPedido.quantidade, ItemPedido.preco_unitario)
        .join(Pedido, Pedido.id == ItemPedido.pedido_id)
        .join(Produto, Produto.id == ItemPedido.produto_id),
        desde, ate,
    ).all()
    return pedidos, itens


# --- andamento do pedido (cozinha e entrega) ---
# um passo por vez; cancelar so antes de sair pra entrega
PROXIMO_STATUS = {"aberto": "em_preparo", "em_preparo": "saiu_entrega", "saiu_entrega": "entregue"}
PODE_CANCELAR = {"aberto", "em_preparo"}
EM_ANDAMENTO = tuple(PROXIMO_STATUS)


def pedidos_em_andamento(db):
    """pedidos que ainda nao foram entregues nem cancelados, do mais antigo pro mais novo, com os itens."""
    return (
        db.query(Pedido)
        .options(joinedload(Pedido.cliente),
                 selectinload(Pedido.itens).joinedload(ItemPedido.produto),
                 selectinload(Pedido.itens).joinedload(ItemPedido.tamanho))
        .filter(Pedido.status.in_(EM_ANDAMENTO))
        .order_by(Pedido.criado_em, Pedido.id)
        .all()
    )


def mudar_status(db, pedido_id, novo):
    """
    avanca ou cancela o pedido. LookupError se ele nao existe; ValueError se o passo nao vale
    (pular etapa, voltar, mexer em pedido entregue ou cancelado).
    """
    pedido = db.get(Pedido, pedido_id)
    if pedido is None:
        raise LookupError("pedido {} nao existe.".format(pedido_id))
    permitido = novo == PROXIMO_STATUS.get(pedido.status) or (novo == "cancelado" and pedido.status in PODE_CANCELAR)
    if not permitido:
        raise ValueError("o pedido {} esta {!r} e nao pode ir para {!r}.".format(pedido_id, pedido.status, novo))
    pedido.status = novo
    db.commit()
    return pedido


def primeiras_compras(db, cliente_ids):
    """data do primeiro pedido de cada cliente: quem comprou pela 1a vez no periodo eh cliente novo."""
    if not cliente_ids:
        return {}
    linhas = (
        _pedidos_validos(db.query(Pedido.cliente_id, func.min(Pedido.criado_em)))
        .filter(Pedido.cliente_id.in_(list(cliente_ids)))
        .group_by(Pedido.cliente_id)
        .all()
    )
    return {cliente_id: primeira for cliente_id, primeira in linhas}


def totais_do_periodo(db, desde=None, ate=None):
    """(quantidade de pedidos, faturamento) de um periodo, pra comparar com o periodo atual."""
    quantidade, faturamento = _pedidos_validos(
        db.query(func.count(Pedido.id), func.coalesce(func.sum(Pedido.total), 0)), desde, ate
    ).one()
    return int(quantidade), Decimal(str(faturamento))
