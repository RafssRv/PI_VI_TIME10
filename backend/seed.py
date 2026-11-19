"""
popula o banco de desenvolvimento com cardapio, clientes e historico de pedidos.

rodar na mao, com o postgres de pe e database/banco.sql ja aplicado:
    python backend/seed.py
    python backend/seed.py --recriar    # apaga tudo antes e popula de novo
    python backend/seed.py --completar  # so acrescenta tamanhos e produtos novos, sem apagar nada

os dados sao ficticios e a semente do random eh fixa, entao todo mundo do time
fica com exatamente o mesmo banco.
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from database import SessionLocal
from models import Cliente, ItemPedido, Pedido, Produto, Tamanho
from seguranca import hashear_cpf

SEMENTE = 10

# (grupo, nome, fatias, desconto). o preco no cardapio eh o do maior tamanho (pizza grande,
# refrigerante de 2 litros); os menores saem com esse desconto em reais
TAMANHOS = [
    ("pizza", "pequena", 4, "25.00"),
    ("pizza", "média", 6, "15.00"),
    ("pizza", "grande", 8, "0.00"),
    ("refrigerante", "Lata", None, "8.90"),
    ("refrigerante", "600 ml", None, "6.90"),
    ("refrigerante", "2 Litros", None, "0.00"),
]

# refrigerante tem lata, 600 ml e 2 litros; agua e suco tem um tamanho so
REFRIGERANTES = {"Coca-Cola", "Guaraná", "Fanta Laranja", "Sprite"}


def grupo_do_tamanho(nome, categoria):
    """qual tabela de tamanhos vale pro produto: pizza, refrigerante ou nenhuma."""
    if categoria.startswith("pizza"):
        return "pizza"
    if nome in REFRIGERANTES:
        return "refrigerante"
    return None

# (nome, descricao, categoria, preco, ativo). preco de pizza = tamanho grande
# preco em string pq Decimal("59.90") eh exato e Decimal(59.90) nao eh
# cada sabor tem uma palavra so dele no nome ("uma de atum", "uma de milho"), senao a fala
# fica ambigua e o atendente precisa perguntar qual eh
CARDAPIO = [
    ("Pizza de Mussarela", "molho de tomate, mussarela e orégano", "pizza salgada", "59.90", True),
    ("Pizza de Calabresa", "calabresa fatiada, cebola e azeitona preta", "pizza salgada", "64.90", True),
    ("Pizza Margherita", "mussarela, tomate em rodelas e manjericão fresco", "pizza salgada", "66.90", True),
    ("Pizza Portuguesa", "presunto, ovo, cebola, ervilha e mussarela", "pizza salgada", "72.90", True),
    ("Pizza de Frango com Catupiry", "frango desfiado com catupiry cremoso", "pizza salgada", "74.90", True),
    ("Pizza Quatro Queijos", "mussarela, provolone, gorgonzola e parmesão", "pizza salgada", "78.90", True),
    ("Pizza de Pepperoni", "mussarela com pepperoni picante", "pizza salgada", "79.90", True),
    ("Pizza Napolitana", "mussarela, tomate, parmesão e orégano", "pizza salgada", "66.90", True),
    ("Pizza Toscana", "calabresa moída, cebola e mussarela", "pizza salgada", "69.90", True),
    ("Pizza Baiana", "calabresa moída apimentada, ovo, cebola e pimenta", "pizza salgada", "69.90", True),
    ("Pizza de Atum", "atum, cebola e azeitona preta", "pizza salgada", "69.90", True),
    ("Pizza de Bacon", "bacon crocante e mussarela", "pizza salgada", "69.90", True),
    ("Pizza de Milho", "milho verde e mussarela", "pizza salgada", "62.90", True),
    ("Pizza de Brócolis", "brócolis, alho frito e mussarela", "pizza salgada", "69.90", True),
    ("Pizza de Palmito", "palmito, mussarela e azeitona", "pizza salgada", "72.90", True),
    ("Pizza de Champignon", "champignon, mussarela e orégano", "pizza salgada", "72.90", True),
    ("Pizza Vegetariana", "brócolis, palmito, milho, ervilha, tomate e mussarela", "pizza salgada", "72.90", True),
    ("Pizza Caipira", "frango desfiado, milho e catupiry", "pizza salgada", "74.90", True),
    ("Pizza de Lombo Canadense", "lombo canadense, cebola e mussarela", "pizza salgada", "74.90", True),
    ("Pizza de Rúcula", "rúcula, tomate seco e mussarela de búfala", "pizza salgada", "76.90", True),
    ("Pizza de Carne Seca", "carne seca desfiada, cebola e catupiry", "pizza salgada", "84.90", True),
    ("Pizza de Camarão", "camarão, catupiry e mussarela", "pizza salgada", "89.90", True),
    # esse sai do cardapio de proposito: caso de teste do ria04, o modelo pode citar mas nao pode vender
    ("Pizza de Escarola com Bacon", "escarola refogada, bacon e mussarela", "pizza salgada", "73.90", False),
    ("Pizza de Chocolate com Morango", "chocolate ao leite e morango fatiado", "pizza doce", "69.90", True),
    ("Pizza de Brigadeiro", "brigadeiro cremoso com granulado", "pizza doce", "64.90", True),
    ("Pizza Romeu e Julieta", "goiabada cremosa com queijo minas", "pizza doce", "62.90", True),
    ("Pizza de Banana com Canela", "banana, açúcar e canela", "pizza doce", "59.90", True),
    ("Pizza Prestígio", "chocolate ao leite e coco ralado", "pizza doce", "66.90", True),
    # refrigerante: preco da garrafa de 2 litros
    ("Coca-Cola", "refrigerante gelado", "bebida", "14.90", True),
    ("Guaraná", "refrigerante gelado", "bebida", "12.90", True),
    ("Fanta Laranja", "refrigerante gelado", "bebida", "12.90", True),
    ("Sprite", "refrigerante gelado", "bebida", "12.90", True),
    ("Suco de Laranja 1 Litro", "suco natural feito na hora", "bebida", "16.90", True),
    ("Água Mineral 500ml", "garrafa de água sem gás", "bebida", "5.00", True),
    ("Água com Gás 500ml", "garrafa de água com gás", "bebida", "5.50", True),
    ("Pudim de Leite", "fatia de pudim de leite condensado", "sobremesa", "15.90", True),
    ("Mousse de Maracujá", "pote individual de mousse", "sobremesa", "14.90", True),
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
        print("o container do postgres subiu e database/banco.sql rodou?")
        raise


def limpar_banco(sessao):
    """apaga tudo na ordem das fks: item, pedido, cliente, produto, tamanho."""
    for modelo in (ItemPedido, Pedido, Cliente, Produto, Tamanho):
        apagadas = sessao.query(modelo).delete()
        print("  {}: {} linhas apagadas".format(modelo.__tablename__, apagadas))
    sessao.commit()


def inserir_tamanhos(sessao):
    """cria os tamanhos e devolve um dicionario (grupo, nome) -> tamanho, ja com id."""
    tamanhos = {}
    for grupo, nome, fatias, desconto in TAMANHOS:
        tamanho = Tamanho(grupo=grupo, nome=nome, fatias=fatias, desconto=Decimal(desconto))
        sessao.add(tamanho)
        tamanhos[(grupo, nome)] = tamanho
    sessao.flush()
    return tamanhos


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
            grupo_tamanho=grupo_do_tamanho(nome, categoria),
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


def inserir_pedidos(sessao, clientes, produtos, tamanhos):
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
                # pizza e refrigerante tem tamanho. a pizza grande e a garrafa de 2 litros sao as
                # mais pedidas, como numa pizzaria de verdade
                tamanho = None
                preco = Decimal(produto.preco)
                if produto.grupo_tamanho == "pizza":
                    nome = random.choices(["grande", "média", "pequena"], weights=[60, 30, 10])[0]
                    tamanho = tamanhos[("pizza", nome)]
                elif produto.grupo_tamanho == "refrigerante":
                    nome = random.choices(["2 Litros", "600 ml", "Lata"], weights=[60, 25, 15])[0]
                    tamanho = tamanhos[("refrigerante", nome)]
                if tamanho is not None:
                    preco -= tamanho.desconto
                pedido.itens.append(
                    ItemPedido(
                        produto_id=produto.id,
                        quantidade=quantidade,
                        # copia do preco do dia da venda, nao aponta pro preco de hoje
                        preco_unitario=preco,
                        observacao=observacao,
                        tamanho_id=tamanho.id if tamanho else None,
                    )
                )
                total += preco * quantidade

            pedido.total = total
            sessao.add(pedido)
            criados += 1

    sessao.flush()
    return criados


def completar(sessao):
    """
    banco que ja tinha dados (clientes e pedidos de teste): acrescenta so o que falta do cardapio
    e dos tamanhos, comparando pelo nome. nao mexe em preco nem apaga nada.
    """
    tamanhos = {(t.grupo, t.nome) for t in sessao.query(Tamanho)}
    novos_tamanhos = [linha for linha in TAMANHOS if (linha[0], linha[1]) not in tamanhos]
    for grupo, nome, fatias, desconto in novos_tamanhos:
        sessao.add(Tamanho(grupo=grupo, nome=nome, fatias=fatias, desconto=Decimal(desconto)))

    produtos = {p.nome: p for p in sessao.query(Produto)}
    novos_produtos = [linha for linha in CARDAPIO if linha[0] not in produtos]
    for nome, descricao, categoria, preco, ativo in novos_produtos:
        sessao.add(Produto(nome=nome, descricao=descricao, categoria=categoria,
                           preco=Decimal(preco), ativo=ativo, grupo_tamanho=grupo_do_tamanho(nome, categoria)))
    # produto que ja existia antes dos tamanhos ganha o grupo dele (a calabresa vira "pizza")
    for nome, _, categoria, _, _ in CARDAPIO:
        if nome in produtos and produtos[nome].grupo_tamanho is None:
            produtos[nome].grupo_tamanho = grupo_do_tamanho(nome, categoria)
    sessao.commit()
    return len(novos_tamanhos), len(novos_produtos)


def main():
    recriar = "--recriar" in sys.argv
    sessao = SessionLocal()
    try:
        if "--completar" in sys.argv:
            tamanhos, produtos = completar(sessao)
            print("acrescentei {} tamanhos e {} produtos; o resto do banco ficou como estava.".format(
                tamanhos, produtos))
            return

        ja_tem = contar_produtos(sessao)
        if ja_tem and not recriar:
            print("o banco ja tem {} produtos, nao vou duplicar nada.".format(ja_tem))
            print("pra apagar tudo e popular de novo: python backend/seed.py --recriar")
            return

        if recriar:
            print("apagando o que ja estava la...")
            limpar_banco(sessao)

        random.seed(SEMENTE)
        tamanhos = inserir_tamanhos(sessao)
        produtos = inserir_produtos(sessao)
        clientes = inserir_clientes(sessao)
        pedidos = inserir_pedidos(sessao, clientes, produtos, tamanhos)
        # um commit so, no final: ou entra tudo ou nao entra nada
        sessao.commit()

        ativos = len([linha for linha in CARDAPIO if linha[4]])
        print("cardapio: {} produtos ({} ativos, {} fora do cardapio)".format(
            len(produtos), ativos, len(produtos) - ativos))
        print("tamanhos: {}".format(", ".join("{} {}".format(g, n) for g, n in tamanhos)))
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
