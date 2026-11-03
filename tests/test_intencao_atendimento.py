"""Regressões de intenção com modelo não confiável, sem Ollama nem PostgreSQL."""

import json
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

import repositorio
from atendimento import Atendimento


def item(produto, quantidade=1, observacao=None):
    return {"produto": produto, "quantidade": quantidade, "observacao": observacao}


class ModeloRoteirizado:
    def __init__(self):
        self.entende()

    def entende(self, itens=(), resposta="O que mais deseja?", fechar=False):
        self.bruto = json.dumps({
            "resposta": resposta, "itens": list(itens), "endereco": None, "fechar": fechar,
        })

    def __call__(self, mensagens, formato=None):
        return self.bruto


@pytest.fixture
def conversa(monkeypatch):
    produtos = [
        SimpleNamespace(id=1, nome="Pizza de Mussarela", preco=Decimal("30.00"),
                        categoria="Pizza salgada", descricao="Queijo e azeitona", ativo=True),
        SimpleNamespace(id=2, nome="Pizza de Calabresa", preco=Decimal("35.00"),
                        categoria="Pizza salgada", descricao="Calabresa e cebola", ativo=True),
        SimpleNamespace(id=3, nome="Água Mineral 500 ml", preco=Decimal("5.00"),
                        categoria="Bebida", descricao="Água sem gás", ativo=True),
        SimpleNamespace(id=4, nome="Coca-Cola 2 Litros", preco=Decimal("12.50"),
                        categoria="Bebida", descricao="Refrigerante", ativo=True),
    ]
    cliente = SimpleNamespace(id=10, nome="Ana Silva", telefone=None, endereco="Rua das Flores, 10")
    gravados = []

    def buscar_produtos(db, nome):
        termo = repositorio._normalizar(nome)
        exatos = [p for p in produtos if repositorio._normalizar(p.nome) == termo]
        return exatos or [p for p in produtos if termo and termo in repositorio._normalizar(p.nome)]

    def salvar_pedido(db, cliente_id, itens, **dados):
        dados["endereco_entrega"] = dados.get("endereco_entrega") or cliente.endereco
        pedido = SimpleNamespace(id=len(gravados) + 1, cliente_id=cliente_id,
                                 itens=deepcopy(itens),
                                 total=sum((i["preco_confirmado"] * i["quantidade"] for i in itens),
                                           Decimal("0.00")), **dados)
        gravados.append(pedido)
        return pedido

    monkeypatch.setattr(repositorio, "listar_cardapio", lambda db, **kwargs: produtos)
    monkeypatch.setattr(repositorio, "buscar_produtos", buscar_produtos)
    monkeypatch.setattr(repositorio, "buscar_cliente_por_cpf", lambda db, cpf: cliente)
    monkeypatch.setattr(repositorio, "salvar_pedido", salvar_pedido)
    monkeypatch.setattr(repositorio, "itens_mais_pedidos_do_cliente",
                        lambda db, cliente_id, limite=3, categoria=None: [(produtos[1], 4)])
    modelo = ModeloRoteirizado()
    atendimento = Atendimento(abrir_sessao=lambda: SimpleNamespace(close=lambda: None),
                              conversar=modelo)
    atendimento.responder("52998224725")
    return SimpleNamespace(atendimento=atendimento, modelo=modelo, gravados=gravados)


def carrinho(conversa):
    return [(i["produto"], i["quantidade"], i["observacao"])
            for i in conversa.atendimento.carrinho]


def pedir(conversa, fala, itens):
    conversa.modelo.entende(itens)
    return conversa.atendimento.responder(fala)


def test_pergunta_de_preco_nao_aceita_produto_que_modelo_adicionou(conversa):
    conversa.modelo.entende([item("Pizza de Mussarela")], resposta="Adicionei a pizza.")

    resposta = conversa.atendimento.responder("Quanto custa a pizza de mussarela?")

    assert carrinho(conversa) == []
    assert "30" in resposta
    assert "mussarela" in resposta.lower()
    assert not conversa.gravados


@pytest.mark.parametrize("saida_modelo", ["vazio", "malformado", "adicao_indevida"])
def test_consulta_preserva_pedido_e_responde_preco(conversa, saida_modelo):
    pedir(conversa, "Quero duas de calabresa sem cebola e uma água", [
        item("Pizza de Calabresa", 2, "sem cebola"), item("Água Mineral 500 ml"),
    ])
    anterior = deepcopy(conversa.atendimento.carrinho)
    if saida_modelo == "malformado":
        conversa.modelo.bruto = "isto não é JSON"
    elif saida_modelo == "adicao_indevida":
        conversa.modelo.entende([item("Pizza de Mussarela", 3)])
    else:
        conversa.modelo.entende([])

    resposta = conversa.atendimento.responder("Qual o preço da mussarela?")

    assert conversa.atendimento.carrinho == anterior
    assert "30" in resposta
    assert "mussarela" in resposta.lower()
    assert "pagar" not in resposta.lower()
    assert "posso confirmar" not in resposta.lower()


def test_recomendacao_nao_adiciona_produto(conversa):
    conversa.modelo.entende([item("Pizza de Calabresa")],
                            resposta="Recomendo a Pizza de Calabresa.")

    resposta = conversa.atendimento.responder("Qual pizza você recomenda?")

    assert carrinho(conversa) == []
    assert resposta
    assert not conversa.gravados


def test_sim_nao_compra_recomendacao_sem_pergunta_de_aceite(conversa):
    conversa.modelo.entende([], resposta="A Pizza de Calabresa é uma opção.")
    conversa.atendimento.responder("Quais opções de pizza vocês recomendam?")
    conversa.modelo.entende([item("Pizza de Calabresa")], resposta="Adicionei.")

    conversa.atendimento.responder("sim")

    assert carrinho(conversa) == []
    assert not conversa.gravados


def test_pedido_nao_aceita_produto_conhecido_que_cliente_nao_pediu(conversa):
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml"), item("Pizza de Calabresa")])

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]


def test_parte_clara_e_preservada_e_duvida_e_especifica(conversa):
    resposta = pedir(conversa, "Quero duas de [incompreensível] e uma água", [
        item("incompreensível", 2), item("Água Mineral 500 ml"),
    ])

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]
    assert "?" in resposta
    assert any(p in resposta.lower() for p in ("sabor", "produto", "pizza"))
    assert conversa.atendimento.etapa != "confirmando_pedido"


def test_esclarecimento_retem_quantidade_ja_dita(conversa):
    pedir(conversa, "Quero duas de [incompreensível] e uma água", [
        item("incompreensível", 2), item("Água Mineral 500 ml"),
    ])

    pedir(conversa, "De mussarela", [item("Pizza de Mussarela"), item("Água Mineral 500 ml")])

    assert sorted(carrinho(conversa)) == [
        ("Pizza de Mussarela", 2, None), ("Água Mineral 500 ml", 1, None),
    ]


def test_erros_consecutivos_pedem_reformulacao_e_preservam_pedido(conversa):
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml")])
    conversa.modelo.bruto = "resposta inválida"

    primeira = conversa.atendimento.responder("[incompreensível]")
    segunda = conversa.atendimento.responder("[incompreensível]")

    assert segunda != primeira
    assert any(p in segunda.lower() for p in ("reformul", "outras palavras", "uma coisa", "por vez"))
    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]
    assert not conversa.gravados


@pytest.mark.parametrize("com_pedido", [False, True])
def test_cardapio_completo_informa_todos_os_produtos_sem_fechar(conversa, com_pedido):
    if com_pedido:
        pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml")])
    anterior = deepcopy(conversa.atendimento.carrinho)
    conversa.modelo.entende([], resposta="Temos várias pizzas.", fechar=True)

    resposta = conversa.atendimento.responder("Quero ouvir o cardápio completo com os preços")

    for nome, precos in [
        ("Pizza de Mussarela", ("30,00", "30 reais")),
        ("Pizza de Calabresa", ("35,00", "35 reais")),
        ("Água Mineral 500 ml", ("5,00", "5 reais")),
        ("Coca-Cola 2 Litros", ("12,50", "12 reais e 50 centavos")),
    ]:
        assert nome.lower() in resposta.lower()
        assert any(preco in resposta for preco in precos)
    assert conversa.atendimento.carrinho == anterior
    assert "pagar" not in resposta.lower()
    assert "posso confirmar" not in resposta.lower()
    assert conversa.atendimento.etapa == "identificado"


def test_adicao_legitima_preserva_itens_e_observacoes(conversa):
    pedir(conversa, "Quero uma calabresa sem cebola", [item("Pizza de Calabresa", 1, "sem cebola")])

    pedir(conversa, "Adicione duas águas", [
        item("Pizza de Calabresa", 1, "sem cebola"), item("Água Mineral 500 ml", 2),
    ])

    assert carrinho(conversa) == [
        ("Pizza de Calabresa", 1, "sem cebola"), ("Água Mineral 500 ml", 2, None),
    ]


def test_remocao_legitima_preserva_outro_item(conversa):
    pedir(conversa, "Quero uma calabresa e duas águas", [
        item("Pizza de Calabresa"), item("Água Mineral 500 ml", 2),
    ])

    pedir(conversa, "Retire as águas", [item("Pizza de Calabresa")])

    assert carrinho(conversa) == [("Pizza de Calabresa", 1, None)]


def test_correcao_de_quantidade_e_observacao_preserva_agua(conversa):
    pedir(conversa, "Quero duas de mussarela e uma água", [
        item("Pizza de Mussarela", 2), item("Água Mineral 500 ml"),
    ])

    pedir(conversa, "Na verdade, só uma mussarela, sem azeitona", [
        item("Pizza de Mussarela", 1, "sem azeitona"), item("Água Mineral 500 ml"),
    ])

    assert carrinho(conversa) == [
        ("Pizza de Mussarela", 1, "sem azeitona"), ("Água Mineral 500 ml", 1, None),
    ]


def test_mais_uma_dessa_ambiguo_nao_deixa_modelo_escolher(conversa):
    pedir(conversa, "Quero uma mussarela e uma calabresa", [
        item("Pizza de Mussarela"), item("Pizza de Calabresa"),
    ])
    anterior = deepcopy(conversa.atendimento.carrinho)
    conversa.modelo.entende([item("Pizza de Mussarela", 2), item("Pizza de Calabresa")])

    resposta = conversa.atendimento.responder("Mais uma dessa")

    assert conversa.atendimento.carrinho == anterior
    assert "?" in resposta
    assert any(p in resposta.lower() for p in ("qual", "produto", "sabor"))


def test_sim_mas_corrige_antes_de_nova_confirmacao(conversa):
    pedir(conversa, "Quero duas de mussarela e uma água, pago no Pix", [
        item("Pizza de Mussarela", 2), item("Água Mineral 500 ml"),
    ])
    conversa.atendimento.responder("Pode fechar")
    assert conversa.atendimento.etapa == "confirmando_pedido"

    resposta = pedir(conversa, "Sim, mas só uma mussarela, sem azeitona", [
        item("Pizza de Mussarela", 1, "sem azeitona"), item("Água Mineral 500 ml"),
    ])

    assert not conversa.gravados
    assert carrinho(conversa) == [
        ("Pizza de Mussarela", 1, "sem azeitona"), ("Água Mineral 500 ml", 1, None),
    ]
    assert "35" in resposta
    assert "?" in resposta
    conversa.atendimento.responder("sim")
    assert len(conversa.gravados) == 1
    assert [(i["produto"], i["quantidade"], i["observacao"]) for i in conversa.gravados[0].itens] == [
        ("Pizza de Mussarela", 1, "sem azeitona"), ("Água Mineral 500 ml", 1, None),
    ]


def test_adicao_nao_perde_item_que_modelo_omitiu(conversa):
    pedir(conversa, "Quero uma calabresa sem cebola", [item("Pizza de Calabresa", 1, "sem cebola")])

    pedir(conversa, "Adicione duas águas", [item("Água Mineral 500 ml", 2)])

    assert carrinho(conversa) == [
        ("Pizza de Calabresa", 1, "sem cebola"), ("Água Mineral 500 ml", 2, None),
    ]


def test_quantidade_e_observacao_inventadas_pelo_modelo_nao_entram(conversa):
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml", 7, "com gelo")])

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]


def test_produto_fora_do_cardapio_nao_e_substituido_por_palpite(conversa):
    conversa.modelo.entende([item("Pizza de Mussarela")], resposta="Adicionei mussarela.")

    resposta = conversa.atendimento.responder("Quero uma pizza de camarão")

    assert carrinho(conversa) == []
    assert "?" in resposta or any(p in resposta.lower() for p in ("não temos", "não consta", "indisponível"))
    assert not conversa.gravados


@pytest.mark.parametrize("fala", [
    "Se eu pedir uma mussarela, quanto vai ficar?",
    "A pizza de mussarela tem azeitona?",
    "Não quero mussarela",
])
def test_mencao_sem_pedido_nao_autoriza_adicao(conversa, fala):
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml")])
    anterior = deepcopy(conversa.atendimento.carrinho)
    conversa.modelo.entende([item("Pizza de Mussarela")])

    conversa.atendimento.responder(fala)

    assert conversa.atendimento.carrinho == anterior


@pytest.mark.parametrize("fala", [
    "A calabresa tem cebola", "Eu gosto de mussarela", "Vocês vendem água",
    "Não sei se quero uma mussarela", "Mussarela é gostosa",
])
def test_mencao_informativa_sem_interrogacao_nao_compra(conversa, fala):
    conversa.modelo.entende([item("Pizza de Mussarela"), item("Água Mineral 500 ml")])
    conversa.atendimento.responder(fala)
    assert carrinho(conversa) == []


def test_produto_mencionado_como_observacao_nao_vira_item(conversa):
    pedir(conversa, "Quero uma calabresa sem mussarela", [
        item("Pizza de Calabresa", observacao="sem mussarela"), item("Pizza de Mussarela"),
    ])
    assert carrinho(conversa) == [("Pizza de Calabresa", 1, "sem mussarela")]


def test_alternativa_nao_escolhe_nem_adiciona_os_dois(conversa):
    resposta = pedir(conversa, "Quero uma mussarela ou uma calabresa", [item("Pizza de Mussarela")])
    assert carrinho(conversa) == []
    assert "?" in resposta


def test_quantidade_fracionada_pede_inteira_e_retem_produto(conversa):
    resposta = pedir(conversa, "Quero meia calabresa", [item("Pizza de Calabresa", 0.5)])
    assert carrinho(conversa) == []
    assert "inteiras" in resposta
    pedir(conversa, "duas", [item("Pizza de Calabresa", 2)])
    assert carrinho(conversa) == [("Pizza de Calabresa", 2, None)]


def test_cardapio_indisponivel_nao_inventa_nem_altera(conversa, monkeypatch):
    from sqlalchemy.exc import OperationalError
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml")])
    anterior = deepcopy(conversa.atendimento.carrinho)

    def indisponivel(*args, **kwargs):
        raise OperationalError("consulta", {}, RuntimeError("banco fora"))

    monkeypatch.setattr(repositorio, "listar_cardapio", indisponivel)
    resposta = conversa.atendimento.responder("Todos os produtos e preços")
    assert conversa.atendimento.carrinho == anterior
    assert "problema" in resposta.lower() or "não consegui" in resposta.lower()
    assert "30" not in resposta and "35" not in resposta


@pytest.mark.parametrize("fala", ["Quero uma água de coco", "Quero uma coca zero",
                                  "Quero uma Coca-Cola 600 ml", "Quero uma água mineral de um litro"])
def test_variante_ausente_nao_vira_produto_parecido(conversa, fala):
    resposta = pedir(conversa, fala, [item("Água Mineral 500 ml"), item("Coca-Cola 2 Litros")])
    assert carrinho(conversa) == []
    assert "?" in resposta


def test_nome_com_preposicao_antes_do_volume_nao_muda_quantidade(conversa):
    pedir(conversa, "Quero uma Coca-Cola de 2 litros", [item("Coca-Cola 2 Litros")])
    assert carrinho(conversa) == [("Coca-Cola 2 Litros", 1, None)]


def test_referencia_inequivoca_usa_ultimo_item_explicitamente_anotado(conversa):
    pedir(conversa, "Quero uma água", [item("Água Mineral 500 ml")])
    pedir(conversa, "Mais uma dessa", [item("Água Mineral 500 ml", 2)])
    assert carrinho(conversa) == [("Água Mineral 500 ml", 2, None)]


def test_grafia_calabreza_observada_no_whisper_real(conversa):
    pedir(conversa, "Quero uma pizza de calabreza", [item("Pizza de Calabresa")])
    assert carrinho(conversa) == [("Pizza de Calabresa", 1, None)]


@pytest.mark.parametrize("fala", ["Não é só isso", "Ainda não terminei"])
def test_negacao_de_fim_nao_forca_resumo(conversa, fala):
    pedir(conversa, "Quero uma água no Pix", [item("Água Mineral 500 ml")])
    resposta = conversa.atendimento.responder(fala)
    assert conversa.atendimento.etapa == "identificado"
    assert "posso confirmar" not in resposta.lower()


def test_nome_ainda_ambiguo_preserva_quantidade_da_pendencia(conversa):
    pedir(conversa, "Quero duas de incompreensível", [])
    pedir(conversa, "pizza", [])
    pedir(conversa, "calabresa", [item("Pizza de Calabresa")])
    assert carrinho(conversa) == [("Pizza de Calabresa", 2, None)]
    assert not conversa.gravados


def test_negacao_de_um_produto_nao_bloqueia_outro_pedido_explicito(conversa):
    pedir(conversa, "Não quero mussarela, quero uma água", [
        item("Pizza de Mussarela"), item("Água Mineral 500 ml"),
    ])

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]


def test_pendencia_de_uma_chamada_nao_altera_quantidade_de_outra(conversa):
    pedir(conversa, "Quero duas de [incompreensível] e uma água", [
        item("incompreensível", 2), item("Água Mineral 500 ml"),
    ])
    outro_modelo = ModeloRoteirizado()
    outro = Atendimento(abrir_sessao=lambda: SimpleNamespace(close=lambda: None),
                        conversar=outro_modelo)
    outro.responder("52998224725")
    outro_modelo.entende([item("Pizza de Mussarela")])

    outro.responder("Quero uma mussarela")

    assert [(i["produto"], i["quantidade"]) for i in outro.carrinho] == [("Pizza de Mussarela", 1)]


@pytest.mark.parametrize("fala", [
    "Não tire a água", "Não retire uma água", "Não quero remover a calabresa",
])
def test_comando_de_remocao_negado_preserva_pedido(conversa, fala):
    pedir(conversa, "Quero duas calabresas e duas águas", [
        item("Pizza de Calabresa", 2), item("Água Mineral 500 ml", 2),
    ])
    anterior = deepcopy(conversa.atendimento.carrinho)
    conversa.modelo.entende([])

    conversa.atendimento.responder(fala)

    assert conversa.atendimento.carrinho == anterior


@pytest.mark.parametrize("fala", [
    "Retire uma água e uma calabresa",
    "Deixe uma água e uma calabresa",
    "Só uma de calabresa e uma água",
])
def test_operacao_compartilhada_nao_vira_adicao_no_segundo_produto(conversa, fala):
    pedir(conversa, "Quero duas calabresas e duas águas", [
        item("Pizza de Calabresa", 2), item("Água Mineral 500 ml", 2),
    ])
    conversa.modelo.entende([])

    resposta = conversa.atendimento.responder(fala)

    quantidades = {i["produto"]: i["quantidade"] for i in conversa.atendimento.carrinho}
    assert set(quantidades) == {"Pizza de Calabresa", "Água Mineral 500 ml"}
    assert all(q in (1, 2) for q in quantidades.values())
    if quantidades != {"Pizza de Calabresa": 1, "Água Mineral 500 ml": 1}:
        assert "?" in resposta  # Uma gramática conservadora precisa esclarecer a parte restante.


def test_correcao_no_fim_da_fala_nao_adiciona_item_negado(conversa):
    pedir(conversa, "Quero duas calabresas e duas águas", [
        item("Pizza de Calabresa", 2), item("Água Mineral 500 ml", 2),
    ])
    conversa.modelo.entende([])

    conversa.atendimento.responder("Uma calabresa e uma água não, só a calabresa")

    agua = next(i for i in conversa.atendimento.carrinho if i["produto"] == "Água Mineral 500 ml")
    assert agua["quantidade"] == 2


@pytest.mark.parametrize("correcao", ["Retire três águas", "Na verdade, só zero águas"])
def test_esclarecer_quantidade_preserva_operacao_pendente(conversa, correcao):
    pedir(conversa, "Quero duas águas", [item("Água Mineral 500 ml", 2)])
    conversa.modelo.entende([])
    resposta = conversa.atendimento.responder(correcao)
    assert "?" in resposta
    assert carrinho(conversa) == [("Água Mineral 500 ml", 2, None)]

    conversa.atendimento.responder("uma")

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]


def test_fragmento_desconhecido_nao_desaparece_ao_reconhecer_outro_produto(conversa):
    conversa.modelo.entende([item("Água Mineral 500 ml")])

    resposta = conversa.atendimento.responder("Quero duas de camarão e uma água")

    assert carrinho(conversa) == [("Água Mineral 500 ml", 1, None)]
    assert "?" in resposta
    assert any(p in resposta.lower() for p in ("camarão", "produto", "sabor"))
    conversa.atendimento.responder("De mussarela")
    assert sorted(carrinho(conversa)) == [
        ("Pizza de Mussarela", 2, None), ("Água Mineral 500 ml", 1, None),
    ]


@pytest.mark.parametrize("fala", ["Quero uma calabresa sem", "Quero uma calabresa sem incompreensível"])
def test_observacao_incompleta_e_esclarecida_sem_duplicar_item(conversa, fala):
    conversa.modelo.entende([item("Pizza de Calabresa")])

    resposta = conversa.atendimento.responder(fala)

    assert carrinho(conversa) == [("Pizza de Calabresa", 1, None)]
    assert "?" in resposta
    conversa.atendimento.responder("cebola")
    assert carrinho(conversa) == [("Pizza de Calabresa", 1, "sem cebola")]


def test_fechamento_negado_nao_pede_confirmacao(conversa):
    pedir(conversa, "Quero duas águas, pago no Pix", [item("Água Mineral 500 ml", 2)])
    conversa.modelo.entende([], fechar=True)

    resposta = conversa.atendimento.responder("Não pode fechar")

    assert conversa.atendimento.etapa == "identificado"
    assert "posso confirmar" not in resposta.lower()
    assert carrinho(conversa) == [("Água Mineral 500 ml", 2, None)]
    assert not conversa.gravados


def test_comando_condicional_sem_interrogacao_nao_edita(conversa):
    pedir(conversa, "Quero duas águas", [item("Água Mineral 500 ml", 2)])
    conversa.modelo.entende([])

    conversa.atendimento.responder("Retire uma água caso eu peça a calabresa")

    assert carrinho(conversa) == [("Água Mineral 500 ml", 2, None)]
