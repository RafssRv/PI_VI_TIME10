"""
roteiro da chamada (atendimento.py): pede o cpf, acha o cliente ou oferece o cadastro,
e so depois passa a conversa pro llama. o llama aqui eh de mentira, entao roda sem ollama.
"""

import json
from decimal import Decimal

import pytest

import repositorio
from models import Pedido
from atendimento import Atendimento, extrair_digitos, extrair_nome, sim_ou_nao

# valido no digito verificador e fora do seed (o mesmo q o seed sugere pra testar o rf04)
CPF_NOVO = "11122233396"


class LlamaDeMentira:
    """
    devolve texto na conversa livre e, quando pedem o json do pedido, o proximo da fila
    (ou um json sem pedido nenhum, se a fila acabou).
    """

    def __init__(self):
        self.chamadas = []
        self.fila = []

    def entende(self, itens=(), endereco=None, fechar=False, resposta="resposta do llama"):
        self.fila.append(json.dumps({
            "resposta": resposta, "itens": list(itens), "endereco": endereco, "fechar": fechar,
        }))

    def __call__(self, mensagens, formato=None):
        self.chamadas.append(mensagens)
        if formato is None:
            return "resposta do llama"
        if self.fila:
            return self.fila.pop(0)
        return json.dumps({"resposta": "resposta do llama", "itens": [], "endereco": None,
                           "fechar": False})


def item(produto, quantidade=1, observacao=None):
    return {"produto": produto, "quantidade": quantidade, "observacao": observacao}


@pytest.fixture
def llama():
    return LlamaDeMentira()


@pytest.fixture
def atendimento(db, llama):
    return Atendimento(abrir_sessao=lambda: db, conversar=llama)


def _cadastrar_ate_confirmar(atendimento):
    atendimento.responder("Olá, tudo bem?")
    atendimento.responder("meu cpf é " + CPF_NOVO)
    atendimento.responder("sim, quero")
    atendimento.responder("Meu nome é joão da silva.")
    atendimento.responder("19 99812 4477")
    return atendimento.responder("Rua das Palmeiras, 120, Centro")


class TestEntendeAFala:
    def test_cpf_formatado(self):
        assert extrair_digitos("é 111.222.333-96") == CPF_NOVO

    def test_cpf_por_extenso(self):
        assert extrair_digitos("um um um dois dois dois tres tres tres nove meia") == CPF_NOVO

    def test_nao_ganha_de_quero(self):
        assert sim_ou_nao("não quero não") is False

    def test_sim(self):
        assert sim_ou_nao("Pode ser!") is True

    def test_nao_entendeu(self):
        assert sim_ou_nao("hmm talvez") is None

    def test_tira_o_meu_nome_e(self):
        assert extrair_nome("Meu nome é maria de souza.") == "Maria de Souza"

    def test_nome_vazio(self):
        assert extrair_nome("é...") is None


class TestIdentificacao:
    def test_cumprimento_pede_o_cpf(self, atendimento):
        resposta = atendimento.responder("Olá, tudo bem?")
        assert "CPF" in resposta
        assert atendimento.etapa == "aguardando_cpf"

    def test_cliente_que_ja_tem_conta(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        resposta = atendimento.responder("meu cpf é " + cpf_da_ana)
        assert "Ana" in resposta
        assert atendimento.etapa == "identificado"
        assert atendimento.cliente_id is not None

    def test_cpf_ja_na_primeira_fala(self, atendimento, cpf_da_ana):
        atendimento.responder("oi, meu cpf é " + cpf_da_ana)
        assert atendimento.etapa == "identificado"

    def test_cpf_invalido_pede_de_novo(self, atendimento):
        atendimento.responder("oi")
        resposta = atendimento.responder("111.222.333-97")
        assert "inválido" in resposta
        assert atendimento.etapa == "aguardando_cpf"

    def test_cpf_incompleto_pede_de_novo(self, atendimento):
        atendimento.responder("oi")
        atendimento.responder("um dois tres")
        assert atendimento.etapa == "aguardando_cpf"

    def test_nao_achou_oferece_cadastro(self, atendimento):
        atendimento.responder("oi")
        resposta = atendimento.responder(CPF_NOVO)
        assert "criar uma conta" in resposta
        assert atendimento.etapa == "oferecendo_cadastro"

    def test_o_cpf_nao_vai_para_o_llama(self, atendimento, llama, cpf_da_ana):
        atendimento.responder("oi, meu cpf é " + cpf_da_ana)
        atendimento.responder("quanto custa a margherita?")
        tudo = str(llama.chamadas)
        assert cpf_da_ana not in tudo


class TestCadastro:
    def test_confirma_os_dados_antes_de_gravar(self, atendimento, db):
        resposta = _cadastrar_ate_confirmar(atendimento)
        assert "João da Silva" in resposta
        assert "(19) 99812-4477" in resposta
        assert "Rua das Palmeiras" in resposta
        assert repositorio.buscar_cliente_por_cpf(db, CPF_NOVO) is None

    def test_cria_a_conta_e_identifica(self, atendimento, db):
        _cadastrar_ate_confirmar(atendimento)
        resposta = atendimento.responder("sim, está certo")

        assert "conta foi criada" in resposta
        assert atendimento.etapa == "identificado"
        cliente = repositorio.buscar_cliente_por_cpf(db, CPF_NOVO)
        assert cliente.nome == "João da Silva"
        assert cliente.telefone == "19998124477"
        assert cliente.endereco == "Rua das Palmeiras, 120, Centro"

    def test_dados_errados_refaz_sem_pedir_cpf(self, atendimento, db):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("não, o nome está errado")
        assert atendimento.etapa == "aguardando_nome"
        assert atendimento.cadastro == {"cpf": CPF_NOVO}
        assert repositorio.buscar_cliente_por_cpf(db, CPF_NOVO) is None

    def test_telefone_e_opcional(self, atendimento, db):
        atendimento.responder("oi")
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder("Carla Mendes")
        atendimento.responder("não tenho telefone")
        atendimento.responder("Avenida Brasil, 500")
        atendimento.responder("sim")
        assert repositorio.buscar_cliente_por_cpf(db, CPF_NOVO).telefone is None

    def test_telefone_curto_pede_de_novo(self, atendimento):
        atendimento.responder("oi")
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder("Carla Mendes")
        atendimento.responder("9981")
        assert atendimento.etapa == "aguardando_telefone"

    def test_recusou_o_cadastro(self, atendimento, db):
        atendimento.responder("oi")
        atendimento.responder(CPF_NOVO)
        resposta = atendimento.responder("não, obrigado")
        assert "não consigo registrar pedidos" in resposta
        assert atendimento.etapa == "sem_cadastro"
        assert repositorio.buscar_cliente_por_cpf(db, CPF_NOVO) is None

    def test_resposta_confusa_pergunta_de_novo(self, atendimento):
        atendimento.responder("oi")
        atendimento.responder(CPF_NOVO)
        atendimento.responder("hmm")
        assert atendimento.etapa == "oferecendo_cadastro"


class TestConversaComOLlama:
    def test_so_entra_depois_de_identificar(self, atendimento, llama, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder(cpf_da_ana)
        assert llama.chamadas == []

        assert atendimento.responder("quais pizzas tem?") == "resposta do llama"
        assert len(llama.chamadas) == 1

    def test_prompt_tem_o_nome_e_o_cardapio(self, atendimento, llama, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento.responder("quais pizzas tem?")
        sistema = llama.chamadas[0][0]
        assert sistema["role"] == "system"
        assert "Ana Beatriz Moraes" in sistema["content"]
        assert "Margherita" in sistema["content"]
        assert "R$" in sistema["content"]

    def test_lembra_da_conversa(self, atendimento, llama, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento.responder("quais pizzas tem?")
        atendimento.responder("e bebidas?")
        mensagens = llama.chamadas[1]
        assert [m["role"] for m in mensagens] == ["system", "user", "assistant", "user"]

    def test_json_quebrado_pede_para_repetir(self, atendimento, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento._conversar = lambda mensagens, formato=None: "isso nao e json"
        assert "repetir" in atendimento.responder("quero uma pizza")
        assert atendimento.historico == []

    def test_sem_conta_conversa_sem_json(self, atendimento, llama):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("não")
        assert atendimento.responder("tem pizza doce?") == "resposta do llama"


@pytest.fixture
def ana_identificada(atendimento, cpf_da_ana):
    atendimento.responder("meu cpf é " + cpf_da_ana)
    assert atendimento.etapa == "identificado"
    return atendimento


def _pedidos_da(db, cliente_id):
    return db.query(Pedido).filter(Pedido.cliente_id == cliente_id).count()


class TestMontaOPedido:
    def test_item_vai_pro_carrinho_com_o_nome_do_cardapio(self, ana_identificada, llama):
        llama.entende([item("margherita", 2)])
        resposta = ana_identificada.responder("quero duas margheritas")
        assert resposta == "resposta do llama"
        assert ana_identificada.carrinho == [{
            "produto": "Pizza Margherita", "quantidade": 2,
            "preco": Decimal("66.90"), "observacao": None,
        }]

    def test_o_llama_ve_o_pedido_atual(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        ana_identificada.responder("e uma coca")
        assert "1 Pizza Margherita" in llama.chamadas[1][0]["content"]

    def test_produto_inventado_vira_aviso(self, ana_identificada, llama):
        llama.entende([item("margherita"), item("pizza de sushi")],
                      resposta="Anotei a pizza de sushi!")
        resposta = ana_identificada.responder("margherita e pizza de sushi")
        assert "Não temos pizza de sushi" in resposta
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]

    def test_produto_desativado_vira_aviso(self, ana_identificada, llama):
        llama.entende([item("Pizza de Escarola com Bacon")])
        assert "Não temos" in ana_identificada.responder("uma de escarola")
        assert ana_identificada.carrinho == []

    def test_produto_vago_vira_pergunta(self, ana_identificada, llama):
        llama.entende([item("borda")])
        resposta = ana_identificada.responder("quero borda")
        assert "Borda de Catupiry ou Borda de Cheddar" in resposta
        assert ana_identificada.carrinho == []

    def test_muito_vago_da_exemplos(self, ana_identificada, llama):
        llama.entende([item("pizza")])
        assert "opções de pizza" in ana_identificada.responder("quero uma pizza")

    def test_quantidade_zero_vira_pergunta(self, ana_identificada, llama):
        llama.entende([item("margherita", 0)])
        assert "Quantas unidades" in ana_identificada.responder("margherita")

    def test_pagamento_falado_vira_o_do_banco(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("margherita no crédito")
        assert ana_identificada.pagamento == "cartao_credito"

    def test_o_pagamento_vem_da_fala_e_nao_do_llama(self, ana_identificada, llama):
        # o llama chutava "credito" quando o cliente so dizia "cartao"
        llama.fila.append(json.dumps({"resposta": "ok", "itens": [item("margherita")],
                                      "pagamento": "cartao_credito", "endereco": None,
                                      "fechar": False}))
        ana_identificada.responder("margherita")
        assert ana_identificada.pagamento is None

    def test_cartao_sem_dizer_qual_pergunta(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        assert "crédito ou de débito" in ana_identificada.responder("no cartão")
        assert ana_identificada.pagamento is None

    def test_pagamento_null_nao_apaga_o_anterior(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        llama.entende([item("margherita"), item("coca cola")])
        ana_identificada.responder("margherita no pix")
        ana_identificada.responder("e uma coca")
        assert ana_identificada.pagamento == "pix"


class TestFechaOPedido:
    def _pedir_e_fechar(self, atendimento, llama, endereco=None,
                        texto="uma margherita e duas cocas no pix, é só isso"):
        llama.entende([item("margherita"), item("coca cola 2 litros", 2)],
                      endereco=endereco, fechar=True)
        return atendimento.responder(texto)

    def test_le_o_resumo_com_total(self, ana_identificada, llama, db):
        resposta = self._pedir_e_fechar(ana_identificada, llama)
        assert "1 Pizza Margherita e 2 Coca-Cola 2 Litros" in resposta
        assert "96 reais e 70 centavos" in resposta
        assert "no Pix" in resposta
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_nao_grava_antes_do_sim(self, ana_identificada, llama, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_sim_grava_o_pedido(self, ana_identificada, llama, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        resposta = ana_identificada.responder("sim, pode confirmar")

        assert "registrado" in resposta
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.total == Decimal("96.70")
        assert pedido.forma_pagamento == "pix"
        assert sorted((i.produto.nome, i.quantidade) for i in pedido.itens) == [
            ("Coca-Cola 2 Litros", 2), ("Pizza Margherita", 1)]
        # sem endereco novo, vai pro endereco do cadastro
        assert pedido.endereco_entrega == pedido.cliente.endereco
        # e o carrinho zera pro proximo pedido
        assert ana_identificada.carrinho == []
        assert ana_identificada.etapa == "identificado"

    def test_endereco_novo_vai_no_pedido(self, ana_identificada, llama, db):
        self._pedir_e_fechar(ana_identificada, llama, endereco="Rua Nova, 45, Cambuí")
        ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.endereco_entrega == "Rua Nova, 45, Cambuí"

    def test_fechar_sem_pagamento_pergunta(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama, texto="margherita e duas cocas, só isso")
        assert ana_identificada.etapa == "identificado"
        assert ana_identificada.historico[-1]["content"].startswith("Como você vai pagar")

    def test_fechar_sem_nada_pergunta(self, ana_identificada, llama):
        llama.entende([], fechar=True)
        assert "não pediu nada" in ana_identificada.responder("é só isso")

    def test_nao_volta_pra_montar(self, ana_identificada, llama, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        assert "mudar" in ana_identificada.responder("não")
        assert ana_identificada.etapa == "identificado"
        assert len(ana_identificada.carrinho) == 2
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_nao_com_correcao_ja_corrige(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama)
        llama.entende([item("margherita")])
        ana_identificada.responder("não, tira as cocas")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]

    def test_resposta_confusa_pergunta_de_novo(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama)
        assert "sim ou não" in ana_identificada.responder("hmm")
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_cliente_novo_tambem_pede(self, atendimento, llama, db):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("sim")
        self._pedir_e_fechar(atendimento, llama)
        atendimento.responder("sim")
        pedido = db.query(Pedido).filter(Pedido.cliente_id == atendimento.cliente_id).one()
        assert pedido.endereco_entrega == "Rua das Palmeiras, 120, Centro"
