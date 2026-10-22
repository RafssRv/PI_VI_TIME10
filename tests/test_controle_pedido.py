from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from agente.controle_pedido import ControlePedido, ErroPedido, ProdutoCardapio


@pytest.fixture
def cardapio():
    return [
        ProdutoCardapio(1, "Pizza de Mussarela", Decimal("30.00")),
        ProdutoCardapio(2, "Pizza de Calabresa", Decimal("35.00")),
        ProdutoCardapio(3, "Água Mineral 500 ml", Decimal("5.00")),
        ProdutoCardapio(4, "Produto desativado", Decimal("10.00"), ativo=False),
    ]


@pytest.fixture
def pedido(cardapio):
    return ControlePedido(cardapio)


def test_correcao_preserva_agua_observacao_e_calcula_35(pedido):
    pizza = pedido.adicionar(1, 2)
    agua = pedido.adicionar(3, 1)
    assert pedido.resumir().subtotal == Decimal("65.00")
    pedido.definir_quantidade(pizza, 1)
    pedido.alterar_observacao(pizza, "sem azeitona")
    resumo = pedido.resumir()
    assert resumo.subtotal == Decimal("35.00")
    assert [(i.id, i.quantidade, i.observacao) for i in resumo.itens] == [
        (pizza, 1, "sem azeitona"), (agua, 1, "")
    ]
    assert "solicitação: sem azeitona" in resumo.texto
    assert "Subtotal dos produtos: R$ 35,00" in resumo.texto


def test_sim_mas_troque_agua_exige_novo_resumo_e_total_60(pedido):
    pizza = pedido.adicionar(1, 1)
    agua = pedido.adicionar(3, 1)
    antigo = pedido.resumir()
    pedido.confirmar(antigo.token)
    assert pedido.confirmado
    assert pedido.substituir(agua, 1, 1, 1) == pizza
    assert not pedido.confirmado
    with pytest.raises(ErroPedido, match="nova confirmação"):
        pedido.confirmar(antigo.token)
    atual = pedido.resumir()
    assert [(i.produto_id, i.quantidade) for i in atual.itens] == [(1, 2)]
    assert atual.subtotal == Decimal("60.00")
    assert "Água" not in atual.texto
    assert "ainda não foi registrado" in pedido.confirmar(atual.token)


def test_troca_parcial_calcula_tres_calabresas_uma_agua_110(pedido):
    pedido.adicionar(2, 2)
    agua = pedido.adicionar(3, 3)
    assert pedido.resumir().subtotal == Decimal("85.00")
    pedido.substituir(agua, 2, 2, 1)
    resumo = pedido.resumir()
    assert [(i.produto_id, i.quantidade) for i in resumo.itens] == [(2, 3), (3, 1)]
    assert resumo.subtotal == Decimal("110.00")


def test_adicao_preserva_observacao_e_subtotal_45(pedido):
    pedido.adicionar(2, 1, "sem cebola")
    pedido.adicionar(3, 2)
    resumo = pedido.resumir()
    assert resumo.itens[0].observacao == "sem cebola"
    assert resumo.itens[1].observacao == ""
    assert resumo.subtotal == Decimal("45.00")


def test_mesmo_produto_com_observacoes_diferentes_nao_se_mistura(pedido):
    normal = pedido.adicionar(1, 1)
    sem_azeitona = pedido.adicionar(1, 1, "sem azeitona")
    assert normal != sem_azeitona
    pedido.adicionar(1, 2, "sem azeitona")
    assert [(i.quantidade, i.observacao) for i in pedido.itens] == [(1, ""), (3, "sem azeitona")]


def test_troca_nao_transfere_observacao_ao_novo_produto(pedido):
    pizza = pedido.adicionar(1, 2, "sem azeitona")
    pedido.substituir(pizza, 1, 3, 1)
    assert [(i.produto_id, i.quantidade, i.observacao) for i in pedido.itens] == [
        (1, 1, "sem azeitona"), (3, 1, "")
    ]


@pytest.mark.parametrize("quantidade", [0, -1, 1.5, 2.0, True, "2", None])
def test_quantidade_invalida_nao_e_arredondada_nem_aceita(pedido, quantidade):
    with pytest.raises(ErroPedido, match="inteira"):
        pedido.adicionar(1, quantidade)
    assert pedido.itens == ()
    assert pedido.pendencia


@pytest.mark.parametrize("produto_id", [999, 4, True, "1"])
def test_produto_inexistente_inativo_ou_id_invalido_bloqueia(pedido, produto_id):
    with pytest.raises(ErroPedido):
        pedido.adicionar(produto_id, 1)
    assert not pedido.itens


def test_troca_invalida_preserva_itens_e_invalida_confirmacao(pedido):
    agua = pedido.adicionar(3, 2)
    antigo = pedido.resumir()
    pedido.confirmar(antigo.token)
    with pytest.raises(ErroPedido, match="não consta"):
        pedido.substituir(agua, 1, 999, 1)
    assert pedido.itens == antigo.itens
    assert not pedido.confirmado
    with pytest.raises(ErroPedido):
        pedido.confirmar(antigo.token)
    with pytest.raises(ErroPedido, match="Esclareça"):
        pedido.resumir()


def test_remover_mais_que_existe_preserva_o_item(pedido):
    agua = pedido.adicionar(3, 1)
    with pytest.raises(ErroPedido, match="excede"):
        pedido.remover(agua, 2)
    assert pedido.itens[0].quantidade == 1


def test_trocar_por_mesmo_produto_atualiza_a_quantidade(pedido):
    agua = pedido.adicionar(3, 3)
    pedido.substituir(agua, 2, 3, 1)
    assert len(pedido.itens) == 1
    assert pedido.itens[0].quantidade == 2
    assert pedido.resumir().subtotal == Decimal("10.00")


@pytest.mark.parametrize("mudanca", ["quantidade", "observacao", "remover", "adicionar"])
def test_alteracoes_invalidam_confirmacao_e_resumo_antigo(pedido, mudanca):
    item = pedido.adicionar(1, 2)
    antigo = pedido.resumir()
    pedido.confirmar(antigo.token)
    if mudanca == "quantidade":
        pedido.definir_quantidade(item, 1)
    elif mudanca == "observacao":
        pedido.alterar_observacao(item, "sem azeitona")
    elif mudanca == "remover":
        pedido.remover(item, 1)
    else:
        pedido.adicionar(3, 1)
    assert not pedido.confirmado
    with pytest.raises(ErroPedido):
        pedido.confirmar(antigo.token)
    assert pedido.resumir().token != antigo.token


def test_duvida_sobre_entrega_bloqueia_confirmacao_sem_inventar_taxa(pedido):
    pedido.adicionar(3, 2)
    antigo = pedido.resumir()
    pedido.definir_pendencia("A pizzaria precisa confirmar a taxa de entrega.")
    with pytest.raises(ErroPedido):
        pedido.confirmar(antigo.token)
    with pytest.raises(ErroPedido, match="taxa"):
        pedido.resumir()
    pedido.definir_pendencia(None)
    atual = pedido.resumir()
    assert atual.subtotal == Decimal("10.00")
    assert atual.token != antigo.token
    assert not pedido.confirmado


def test_operacao_valida_nao_apaga_duvida_anterior(pedido):
    pedido.definir_pendencia("Qual sabor da segunda pizza?")
    pedido.adicionar(3, 1)
    assert pedido.pendencia == "Qual sabor da segunda pizza?"
    with pytest.raises(ErroPedido):
        pedido.resumir()


def test_nao_confirma_sem_resumo(pedido):
    pedido.adicionar(1, 1)
    with pytest.raises(ErroPedido):
        pedido.confirmar("token-inventado")
    assert not pedido.confirmado


def test_resumo_de_outra_conversa_nao_confirma(cardapio):
    primeiro = ControlePedido(cardapio)
    segundo = ControlePedido(cardapio)
    primeiro.adicionar(1, 1)
    segundo.adicionar(1, 1)
    segundo.resumir()
    with pytest.raises(ErroPedido):
        segundo.confirmar(primeiro.resumir().token)
    assert not segundo.confirmado


def test_desistencia_remove_tudo_sem_simular_cancelamento_no_banco(pedido):
    pedido.adicionar(1, 1)
    resumo = pedido.resumir()
    pedido.confirmar(resumo.token)
    assert pedido.limpar() == "Retirei os itens do resumo. Nenhum pedido foi registrado."
    assert pedido.itens == () and not pedido.confirmado
    with pytest.raises(ErroPedido, match="Não há itens"):
        pedido.resumir()
    with pytest.raises(ErroPedido):
        pedido.confirmar(resumo.token)


def test_retirar_ultimo_item_deixa_resumo_vazio(pedido):
    item = pedido.adicionar(1, 1)
    pedido.remover(item, 1)
    with pytest.raises(ErroPedido, match="Não há itens"):
        pedido.resumir()


def test_dinheiro_com_centavos_nao_usa_float():
    controle = ControlePedido([ProdutoCardapio(1, "Produto", Decimal("0.10"))])
    controle.adicionar(1, 3)
    assert controle.resumir().subtotal == Decimal("0.30")
    assert "R$ 0,30" in controle.resumir().texto


@pytest.mark.parametrize("preco", [30.0, Decimal("NaN"), Decimal("Infinity"), Decimal("-1.00"), Decimal("1.001")])
def test_preco_invalido_do_catalogo_nao_entra(preco):
    with pytest.raises(ErroPedido, match="preço"):
        ControlePedido([ProdutoCardapio(1, "Produto", preco)])


def test_cardapio_com_ids_duplicados_nao_sobrescreve_preco():
    with pytest.raises(ErroPedido, match="duplicados"):
        ControlePedido([
            ProdutoCardapio(1, "Produto", Decimal("30.00")),
            ProdutoCardapio(1, "Outro produto", Decimal("1.00")),
        ])


def test_resumo_e_snapshot_nao_muda_depois_de_correcao(pedido):
    item = pedido.adicionar(1, 1)
    antigo = pedido.resumir()
    pedido.definir_quantidade(item, 2)
    assert antigo.subtotal == Decimal("30.00")
    assert pedido.resumir().subtotal == Decimal("60.00")
    with pytest.raises(FrozenInstanceError):
        antigo.itens[0].quantidade = 100


def test_confirmacao_repetida_e_idempotente(pedido):
    pedido.adicionar(1, 1)
    resumo = pedido.resumir()
    primeira = pedido.confirmar(resumo.token)
    assert pedido.confirmar(resumo.token) == primeira
    assert pedido.resumir() is resumo
    assert pedido.confirmado
