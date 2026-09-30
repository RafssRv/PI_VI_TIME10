"""
popula o banco de desenvolvimento com cardapio, clientes e historico de pedidos.

rodar na mao, com o postgres de pe e o banco.sql ja aplicado:
    python backend/seed.py
    python backend/seed.py --recriar   # apaga tudo antes e popula de novo

os dados sao ficticios e a semente do random eh fixa, entao todo mundo do time
fica com exatamente o mesmo banco.
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from database import SessionLocal
from models import Cliente, ItemPedido, Pedido, Produto
from seguranca import hashear_cpf

SEMENTE = 10

# (nome, descricao, categoria, preco, ativo)
# preco em string pq Decimal("59.90") eh exato e Decimal(59.90) nao eh
CARDAPIO = [
    ("Pizza de Mussarela", "molho de tomate, mussarela e oregano", "pizza salgada", "59.90", True),
    ("Pizza de Calabresa", "calabresa fatiada, cebola e azeitona preta", "pizza salgada", "64.90", True),
    ("Pizza Margherita", "mussarela, tomate em rodelas e manjericao fresco", "pizza salgada", "66.90", True),
    ("Pizza Portuguesa", "presunto, ovo, cebola, ervilha e mussarela", "pizza salgada", "72.90", True),
    ("Pizza de Frango com Catupiry", "frango desfiado com catupiry cremoso", "pizza salgada", "74.90", True),
    ("Pizza Quatro Queijos", "mussarela, provolone, gorgonzola e parmesao", "pizza salgada", "78.90", True),
    ("Pizza de Pepperoni", "mussarela com pepperoni picante", "pizza salgada", "79.90", True),
    # esse sai do cardapio de proposito: caso de teste do ria04, o modelo pode citar mas nao pode vender
    ("Pizza de Escarola com Bacon", "escarola refogada, bacon e mussarela", "pizza salgada", "73.90", False),
    ("Pizza de Chocolate com Morango", "chocolate ao leite e morango fatiado", "pizza doce", "69.90", True),
    ("Pizza de Brigadeiro", "brigadeiro cremoso com granulado", "pizza doce", "64.90", True),
    ("Pizza Romeu e Julieta", "goiabada cremosa com queijo minas", "pizza doce", "62.90", True),
    ("Coca-Cola 2 Litros", "refrigerante gelado, garrafa de 2 litros", "bebida", "14.90", True),
    ("Guarana 2 Litros", "refrigerante gelado, garrafa de 2 litros", "bebida", "12.90", True),
    ("Suco de Laranja 1 Litro", "suco natural feito na hora", "bebida", "16.90", True),
    ("Agua Mineral 500ml", "garrafa de agua sem gas", "bebida", "5.00", True),
    ("Pudim de Leite", "fatia de pudim de leite condensado", "sobremesa", "15.90", True),
    ("Mousse de Maracuja", "pote individual de mousse", "sobremesa", "14.90", True),
    ("Borda de Catupiry", "borda recheada com catupiry", "borda", "12.00", True),
    ("Borda de Cheddar", "borda recheada com cheddar", "borda", "12.00", True),
]

# (nome, telefone, endereco, 9 primeiros digitos do cpf)
# os 2 digitos verificadores sao calculados aqui embaixo, senao o hashear_cpf recusa
CLIENTES = [
    ("Ana Beatriz Moraes", "(19) 99812-4477",
     "Rua Barao de Jaguara, 1200, apto 52 - Centro, Campinas/SP", "382914756"),
    ("Carlos Eduardo Lima", "(19) 99705-3321",
     "Avenida Doutor Moraes Salles, 480 - Cambui, Campinas/SP", "517426083"),
    ("Juliana Ferreira Souza", "(19) 98844-1907",
     "Rua Doutor Sampaio Ferraz, 310, casa 2 - Taquaral, Campinas/SP", "246178395"),
    ("Marcos Antonio Pereira", "(19) 99123-8865",
     "Avenida Albino Jose Barbosa de Oliveira, 1975 - Barao Geraldo, Campinas/SP", "693052841"),
    ("Renata Alves Caldeira", "(19) 98730-5512",
     "Rua Coronel Quirino, 842, apto 14 - Cambui, Campinas/SP", "158390472"),
    ("Thiago Nogueira Ramos", "(19) 99566-2048",
     "Rua Sao Paulo, 66 - Jardim Chapadao, Campinas/SP", "874261539"),
]

# (indice do cliente, quantos pedidos, produto favorito)
# o favorito entra em TODO pedido do cliente. sem esse padrao a recomendacao do rf08
# nao tem o q recomendar, ia ver so itens soltos
PERFIS = [
    (0, 10, "Pizza de Calabresa"),
    (1, 7, "Pizza de Frango com Catupiry"),
    (2, 5, "Pizza Quatro Queijos"),
    (3, 4, "Pizza Portuguesa"),
    (4, 3, "Pizza de Chocolate com Morango"),
    (5, 1, "Pizza de Mussarela"),
]

FORMAS_PAGAMENTO = ["pix", "dinheiro", "cartao_credito", "cartao_debito"]

OBSERVACOES = [
    "sem cebola",
    "bem assada",
    "cortada em 8 pedacos",
    "capricha no catupiry",
    "sem azeitona",
    "massa fina",
    "mandar guardanapo",
]


def gerar_cpf(base):
    """recebe os 9 primeiros digitos e devolve o cpf completo, com os 2 dv certos."""
    digitos = [int(c) for c in base]
    for quantidade in (9, 10):
        soma = 0
        peso = quantidade + 1
        for numero in digitos[:quantidade]:
            soma += numero * peso
            peso -= 1
        resto = (soma * 10) % 11
        digitos.append(0 if resto == 10 else resto)
    return "".join(str(d) for d in digitos)


def formatar_cpf(cpf):
    """so pra imprimir bonito no final: 12345678909 vira 123.456.789-09"""
    return "{}.{}.{}-{}".format(cpf[:3], cpf[3:6], cpf[6:9], cpf[9:])


def contar_produtos(sessao):
    """conta o cardapio. se a tabela nem existe, avisa o q falta antes de estourar."""
    try:
        return sessao.query(Produto).count()
    except Exception:
        sessao.rollback()
        print("ERRO: nao consegui ler a tabela produto.")
        print("o container do postgres subiu e o banco.sql rodou?")
        raise


def limpar_banco(sessao):
    """apaga tudo na ordem das fks: item, pedido, cliente, produto."""
    for modelo in (ItemPedido, Pedido, Cliente, Produto):
        apagadas = sessao.query(modelo).delete()
        print("  {}: {} linhas apagadas".format(modelo.__tablename__, apagadas))
    sessao.commit()


def inserir_produtos(sessao):
    """cria o cardapio e devolve a lista de produtos, ja com id."""
    produtos = []
    for nome, descricao, categoria, preco, ativo in CARDAPIO:
        produto = Produto(
            nome=nome,
            descricao=descricao,
            categoria=categoria,
            preco=Decimal(preco),
            ativo=ativo,
        )
        sessao.add(produto)
        produtos.append(produto)
    # flush e nao commit: so quero os ids na mao pros itens do pedido
    sessao.flush()
    return produtos


def inserir_clientes(sessao):
    """cria os clientes e devolve lista de (cliente, cpf em texto)."""
    criados = []
    for nome, telefone, endereco, base in CLIENTES:
        cpf = gerar_cpf(base)
        cliente = Cliente(
            nome=nome,
            telefone=telefone,
            endereco=endereco,
            # o numero puro nunca vai pro banco (rnf06), so o hmac dele
            cpf_hash=hashear_cpf(cpf),
        )
        sessao.add(cliente)
        criados.append((cliente, cpf))
    sessao.flush()
    return criados


def inserir_pedidos(sessao, clientes, produtos):
    """monta o historico dos ultimos meses. devolve quantos pedidos criou."""
    por_nome = {produto.nome: produto for produto in produtos}
    # produto desativado nunca entra em pedido, ele so existe no cardapio como caso de teste
    disponiveis = [produto for produto in produtos if produto.ativo]
    agora = datetime.now(timezone.utc)
    criados = 0

    for indice, quantos, nome_favorito in PERFIS:
        cliente = clientes[indice][0]
        favorito = por_nome[nome_favorito]
        extras_possiveis = [p for p in disponiveis if p.nome != nome_favorito]

        for _ in range(quantos):
            # data em datetime do python mesmo. a coluna eh timestamptz, entao vai com fuso
            momento = agora - timedelta(
                days=random.randint(2, 150),
                hours=random.randint(0, 6),
                minutes=random.randint(0, 59),
            )
            pedido = Pedido(
                cliente_id=cliente.id,
                endereco_entrega=cliente.endereco,
                forma_pagamento=random.choice(FORMAS_PAGAMENTO),
                status="concluido",
                criado_em=momento,
            )

            escolhidos = [favorito] + random.sample(extras_possiveis, random.randint(0, 3))

            total = Decimal("0.00")
            for produto in escolhidos:
                quantidade = random.choices([1, 2, 3], weights=[70, 25, 5])[0]
                observacao = random.choice(OBSERVACOES) if random.random() < 0.25 else None
                pedido.itens.append(
                    ItemPedido(
                        produto_id=produto.id,
                        quantidade=quantidade,
                        # copia do preco do dia da venda, nao aponta pro preco de hoje
                        preco_unitario=produto.preco,
                        observacao=observacao,
                    )
                )
                total += produto.preco * quantidade

            pedido.total = total
            sessao.add(pedido)
            criados += 1

    sessao.flush()
    return criados


def main():
    recriar = "--recriar" in sys.argv
    sessao = SessionLocal()
    try:
        ja_tem = contar_produtos(sessao)
        if ja_tem and not recriar:
            print("o banco ja tem {} produtos, nao vou duplicar nada.".format(ja_tem))
            print("pra apagar tudo e popular de novo: python backend/seed.py --recriar")
            return

        if recriar:
            print("apagando o que ja estava la...")
            limpar_banco(sessao)

        random.seed(SEMENTE)
        produtos = inserir_produtos(sessao)
        clientes = inserir_clientes(sessao)
        pedidos = inserir_pedidos(sessao, clientes, produtos)
        # um commit so, no final: ou entra tudo ou nao entra nada
        sessao.commit()

        ativos = len([linha for linha in CARDAPIO if linha[4]])
        print("cardapio: {} produtos ({} ativos, {} fora do cardapio)".format(
            len(produtos), ativos, len(produtos) - ativos))
        print("clientes: {}".format(len(clientes)))
        print("pedidos: {} concluidos, espalhados pelos ultimos 5 meses".format(pedidos))
        print("")
        print("cpfs pra testar a identificacao por voz (rf03):")
        for cliente, cpf in clientes:
            print("  {:<24} {}".format(cliente.nome, formatar_cpf(cpf)))
        print("")
        print("cpf que NAO esta no banco, pra testar o cadastro do rf04: {}".format(
            formatar_cpf(gerar_cpf("111222333"))))
        print("produto inativo pro teste do ria04: Pizza de Escarola com Bacon")
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


if __name__ == "__main__":
    main()
