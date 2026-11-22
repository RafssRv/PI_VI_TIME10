"""
roteiro da chamada (atendimento.py): pede o cpf, acha o cliente ou oferece o cadastro,
e so depois passa a conversa pro llama. o llama aqui eh de mentira, entao roda sem ollama.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

import repositorio
import seed
from models import Pedido
from atendimento import Atendimento
from interpretacao import extrair_digitos, extrair_nome, juntar_segmentos, parece_confirmacao, sim_ou_nao

# valido no digito verificador e fora do seed (o mesmo q o seed sugere pra testar o rf04)
CPF_NOVO = "11122233396"
# o codigo nao resolve sozinho, entao ainda depende do modelo: serve pra testar a falha dele
FALA_QUE_PRECISA_DO_MODELO = "não, a entrega é no meu trabalho"


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
        assert "não ouvi direito" in resposta
        assert atendimento.etapa == "aguardando_cpf"

    def test_cpf_incompleto_pede_de_novo(self, atendimento):
        atendimento.responder("oi")
        atendimento.responder("um dois tres")
        assert atendimento.etapa == "aguardando_cpf"

    def test_nao_achou_oferece_cadastro(self, atendimento):
        atendimento.responder("oi")
        resposta = atendimento.responder(CPF_NOVO)
        assert "criar agora" in resposta
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

        assert atendimento.responder("vocês abrem amanhã?") == "resposta do llama"
        assert len(llama.chamadas) == 1

    def test_prompt_tem_o_nome_e_o_cardapio(self, atendimento, llama, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento.responder("vocês abrem amanhã?")
        sistema = llama.chamadas[0][0]
        assert sistema["role"] == "system"
        assert "Ana Beatriz Moraes" in sistema["content"]
        assert "Margherita" in sistema["content"]
        assert "R$" in sistema["content"]

    def test_lembra_da_conversa(self, atendimento, llama, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento.responder("vocês abrem amanhã?")
        atendimento.responder("e no domingo?")
        mensagens = llama.chamadas[1]
        assert [m["role"] for m in mensagens] == ["system", "user", "assistant", "user"]

    def test_json_quebrado_pede_para_repetir(self, atendimento, cpf_da_ana):
        atendimento.responder(cpf_da_ana)
        atendimento._conversar = lambda mensagens, formato=None: "isso nao e json"
        assert atendimento.responder("a entrega é no meu trabalho")
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
        resposta = ana_identificada.responder("quero duas margheritas grandes")
        assert "Quer algo mais?" in resposta
        assert "pagar" not in resposta
        assert ana_identificada.carrinho == [{
            "produto": "Pizza Margherita", "quantidade": 2,
            "preco": Decimal("66.90"), "observacao": None, "tamanho": "grande",
        }]

    def test_o_llama_ve_o_pedido_atual(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        ana_identificada.responder("a entrega é no meu trabalho")
        assert "1 Pizza Margherita" in llama.chamadas[0][0]["content"]

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
        assert "Qual sabor" in ana_identificada.responder("quero uma pizza")

    def test_quantidade_zero_vira_pergunta(self, ana_identificada, llama):
        llama.entende([item("margherita", 0)])
        assert "Quantas unidades" in ana_identificada.responder("zero margheritas")

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
        assert "Crédito ou débito" in ana_identificada.responder("no cartão")
        assert ana_identificada.pagamento is None

    def test_pagamento_null_nao_apaga_o_anterior(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        llama.entende([item("margherita"), item("coca cola")])
        ana_identificada.responder("margherita no pix")
        ana_identificada.responder("e uma coca de 2 litros")
        assert ana_identificada.pagamento == "pix"


class TestFechaOPedido:
    @pytest.mark.parametrize("fala", [
        "Sim, mas troque a água por mais uma margherita.",
        "Pode trocar 1 água mineral por 1 Pizza Margherita?",
        "Substitua uma água por uma margherita, por favor.",
    ])
    def test_troca_explicita_retira_agua_e_soma_so_a_nova_pizza(
        self, ana_identificada, llama, db, fala,
    ):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        llama.entende([item("margherita"), item("água mineral")])
        ana_identificada.responder("Uma margherita grande e uma água mineral no pix, é só isso")

        def nao_deve_reconstruir_carrinho(*args, **kwargs):
            raise AssertionError("A troca explícita não precisa da interpretação do LLM")

        ana_identificada._conversar = nao_deve_reconstruir_carrinho
        resposta = ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [
            ("Pizza Margherita", 2)]
        assert "133 reais e 80 centavos" in resposta
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes
        assert "confirmado" in ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.total == Decimal("133.80")
        assert [(i.produto.nome, i.quantidade) for i in pedido.itens] == [("Pizza Margherita", 2)]

    def test_troca_parcial_preserva_resto_e_nao_transfere_observacao(self, ana_identificada, llama):
        llama.entende([item("margherita", 2, "sem tomate"), item("água mineral", 3)])
        ana_identificada.responder("Duas margheritas grandes sem tomate e três águas minerais no pix")
        resposta = ana_identificada.responder("Troque duas águas por uma margherita")
        assert [(i["produto"], i["quantidade"], i["observacao"])
                for i in ana_identificada.carrinho] == [
            ("Pizza Margherita", 2, "sem tomate"), ("Água Mineral 500ml", 1, None),
            ("Pizza Margherita", 1, None)]
        assert "Quer algo mais?" in resposta
        assert "205 reais e 70 centavos" in ana_identificada.responder("pode fechar")

    @pytest.mark.parametrize("fala", [
        "Troque quatro cocas por uma água", "Troque uma coca e meia por uma água",
        "Troque uma coca por meia água", "Troque uma coca por zero águas",
        "Troque uma coca por uma pizza de sushi", "Troque uma coca por uma pizza",
        "Troque uma coca por uma água e acrescente uma margherita",
        "Troque a água por uma margherita", "Troque as cocas por uma água",
        "Troque uma coca por água", "Troque por uma água",
        "Não troque uma coca por uma água", "Se for possível, troque uma coca por uma água",
        "Troque -1 coca por uma água", "Troque uma coca por -1 água",
    ])
    def test_troca_nao_esclarecida_preserva_carrinho_e_bloqueia_confirmacao(
        self, ana_identificada, llama, db, fala,
    ):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        ana_identificada.responder(fala)
        assert ana_identificada.carrinho == anterior
        ana_identificada.responder("sim")
        ana_identificada.responder("sim")
        assert ana_identificada.etapa == "identificado"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_troca_com_origem_ambigua_preserva_observacoes(self, ana_identificada, llama):
        llama.entende([item("margherita", observacao="sem tomate"),
                      item("margherita", observacao="sem manjericão")])
        ana_identificada.responder("Uma margherita sem tomate e uma margherita sem manjericão no pix")
        anterior = list(ana_identificada.carrinho)
        resposta = ana_identificada.responder("Troque uma margherita por uma água")
        assert ana_identificada.carrinho == anterior
        assert "qual" in resposta.lower()
        assert "qual" in ana_identificada.responder("sim").lower()

    def test_troca_sem_pedido_nao_vira_inclusao(self, ana_identificada):
        resposta = ana_identificada.responder("Troque uma água por uma margherita")
        assert ana_identificada.carrinho == []
        assert "trocar" in resposta

    def test_troca_pendente_exige_frase_completa_para_nao_apagar_pedido(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        ana_identificada.responder("Troque as cocas por uma água")
        ana_identificada.responder("duas")
        ana_identificada.responder("sim")
        assert ana_identificada.carrinho == anterior
        assert ana_identificada.etapa == "identificado"
        resposta = ana_identificada.responder("Troque duas cocas de 2 litros por uma água mineral")
        assert "71 reais e 90 centavos" in resposta
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_desistir_da_troca_preserva_itens_e_exige_nova_confirmacao(self, ana_identificada, llama, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        ana_identificada.responder("Troque as cocas por uma água")
        resposta = ana_identificada.responder("cancele a troca")
        assert ana_identificada.carrinho == anterior
        assert "96 reais e 70 centavos" in resposta
        assert ana_identificada.etapa == "confirmando_pedido"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    @pytest.mark.parametrize("ultima_fala", ["cancele a troca", "troque uma coca por uma água mineral"])
    def test_troca_nao_apaga_duvida_anterior(self, ana_identificada, llama, db, ultima_fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        llama.entende([item("margherita"), item("coca cola 2 litros", 2), item("borda")])
        pendencia = ana_identificada.responder("acrescente uma borda")
        assert "Catupiry ou Borda de Cheddar" in pendencia
        ana_identificada.responder("quero trocar")
        assert ana_identificada.responder(ultima_fala) == pendencia
        assert pendencia in ana_identificada.responder("sim")
        assert ana_identificada.etapa == "identificado"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_sim_apos_pergunta_do_modelo_nao_escolhe_produto(self, ana_identificada, llama):
        llama.entende([], resposta="Qual pizza você deseja?")
        ana_identificada.responder("uma pizza")
        assert "sabor" in ana_identificada.responder("sim")
        assert llama.chamadas == []
        assert ana_identificada.carrinho == []

    def test_condicao_comercial_nao_e_inventada(self, ana_identificada, llama):
        resposta = ana_identificada.responder("a entrega é grátis?")
        assert "pizzaria precisa confirmar" in resposta
        assert llama.chamadas == []

    def test_erro_do_ollama_nao_deixa_turno_incompleto(self, ana_identificada):
        def indisponivel(*args, **kwargs):
            raise TimeoutError("Ollama indisponível")
        ana_identificada._conversar = indisponivel
        with pytest.raises(TimeoutError):
            ana_identificada.responder("a entrega é no meu trabalho")
        assert ana_identificada.historico == []

    @pytest.mark.parametrize("fala", ["sim, mas tire as cocas", "sim, a entrega é grátis?",
                                      "pode trocar as cocas por água", "sim?"])
    def test_confirmacao_com_ressalva_nao_grava(self, ana_identificada, llama, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        llama.entende([item("margherita")], fechar=True)
        ana_identificada.responder(fala)
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_observacoes_distintas_aparecem_no_resumo(self, ana_identificada, llama):
        llama.entende([item("margherita", observacao="sem tomate"),
                      item("margherita", observacao="sem manjericão")], fechar=True)
        resposta = ana_identificada.responder("uma margherita sem tomate e uma margherita sem manjericão no pix, só isso")
        assert "sem tomate" in resposta and "sem manjericão" in resposta
        assert len(ana_identificada.carrinho) == 2

    def test_troca_invalida_preserva_pedido(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        ana_identificada.responder("sim, mas troque a margherita por uma pizza de sushi")
        assert ana_identificada.carrinho == anterior
        assert ana_identificada.etapa == "identificado"
        assert "Não temos" in ana_identificada.responder("sim")

    def test_json_incompleto_preserva_pedido(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        llama.fila.append('{"resposta": "ok"}')
        ana_identificada.responder("não, quero corrigir")
        assert ana_identificada.carrinho == anterior

    @pytest.mark.parametrize("falha", ["json_invalido", "json_incompleto", "timeout"])
    def test_falha_na_correcao_exige_esclarecimento_antes_de_confirmar(
        self, ana_identificada, llama, db, falha,
    ):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._pedir_e_fechar(ana_identificada, llama)
        anterior = list(ana_identificada.carrinho)
        historico = list(ana_identificada.historico)

        def resposta_com_falha(mensagens, formato=None):
            if falha == "timeout":
                raise TimeoutError("Ollama indisponível")
            return "isso não é JSON" if falha == "json_invalido" else '{"resposta": "ok"}'

        ana_identificada._conversar = resposta_com_falha
        if falha == "timeout":
            with pytest.raises(TimeoutError):
                ana_identificada.responder(FALA_QUE_PRECISA_DO_MODELO)
        else:
            assert "repetir" in ana_identificada.responder(FALA_QUE_PRECISA_DO_MODELO)

        assert ana_identificada.carrinho == anterior
        assert ana_identificada.historico == historico
        for fala in ("sim", "é só isso", "sim"):
            resposta = ana_identificada.responder(fala)
            assert _pedidos_da(db, ana_identificada.cliente_id) == antes
            assert "repetir" in resposta
            assert ana_identificada.etapa == "identificado"
        assert ana_identificada.carrinho == anterior

        # Só uma correção válida permite apresentar e confirmar outro resumo.
        ana_identificada._conversar = llama
        llama.entende([item("margherita")])
        resposta = ana_identificada.responder("tire as cocas")
        assert "66 reais e 90 centavos" in resposta
        assert ana_identificada.etapa == "confirmando_pedido"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

        assert "confirmado" in ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1
        assert pedido.total == Decimal("66.90")
        assert [(i.produto.nome, i.quantidade) for i in pedido.itens] == [("Pizza Margherita", 1)]

    def test_preco_alterado_exige_novo_resumo(self, ana_identificada, llama, db):
        self._pedir_e_fechar(ana_identificada, llama)
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        produto = repositorio.buscar_produtos(db, "margherita")[0]
        antigo = produto.preco
        try:
            produto.preco = Decimal("70.00")
            db.commit()
            resposta = ana_identificada.responder("sim")
            assert _pedidos_da(db, ana_identificada.cliente_id) == antes
            assert "99 reais e 80 centavos" in resposta
            assert ana_identificada.etapa == "confirmando_pedido"
        finally:
            produto = repositorio.buscar_produtos(db, "margherita")[0]
            produto.preco = antigo
            db.commit()

    def _pedir_e_fechar(self, atendimento, llama, endereco=None,
                        texto="uma margherita grande e duas cocas de 2 litros no pix, é só isso"):
        llama.entende([item("margherita"), item("coca cola 2 litros", 2)],
                      endereco=endereco, fechar=True)
        return atendimento.responder(texto)

    def test_le_o_resumo_com_total(self, ana_identificada, llama, db):
        resposta = self._pedir_e_fechar(ana_identificada, llama)
        assert "1 Pizza Margherita grande e 2 Coca-Cola 2 Litros" in resposta
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

        assert "confirmado" in resposta
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.total == Decimal("96.70")
        assert pedido.forma_pagamento == "pix"
        assert sorted((i.produto.nome, i.quantidade) for i in pedido.itens) == [
            ("Coca-Cola", 2), ("Pizza Margherita", 1)]
        # sem endereco novo, vai pro endereco do cadastro
        assert pedido.endereco_entrega == pedido.cliente.endereco
        # e o carrinho zera pro proximo pedido
        assert ana_identificada.carrinho == []
        assert ana_identificada.etapa == "identificado"

    def test_pedido_gravado_continua_conhecido_depois_de_comecar_outro(self, ana_identificada, llama, db):
        assert ana_identificada.ultimo_pedido_id is None
        self._pedir_e_fechar(ana_identificada, llama)
        ana_identificada.responder("sim, pode confirmar")
        gravado = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                   .order_by(Pedido.id.desc()).first())
        ana_identificada.responder("quero mais uma coca lata")
        # a comanda ja eh do pedido novo, mas o monitor ainda precisa do que foi gravado
        assert ana_identificada._pedido_salvo is None
        assert ana_identificada.ultimo_pedido_id == gravado.id

    def test_endereco_novo_vai_no_pedido(self, ana_identificada, llama, db):
        self._pedir_e_fechar(ana_identificada, llama, endereco="Rua Nova, 45, Cambuí",
                            texto="uma margherita grande e duas cocas de 2 litros no pix, entrega na Rua Nova, 45, Cambuí, é só isso")
        ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.endereco_entrega == "Rua Nova, 45, Cambuí"

    def test_fechar_sem_pagamento_pergunta(self, ana_identificada, llama):
        self._pedir_e_fechar(ana_identificada, llama, texto="margherita grande e duas cocas de 2 litros, só isso")
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
        assert "Posso confirmar" in ana_identificada.responder("hmm")
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_cliente_novo_tambem_pede(self, atendimento, llama, db):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("sim")
        self._pedir_e_fechar(atendimento, llama)
        atendimento.responder("sim")
        pedido = db.query(Pedido).filter(Pedido.cliente_id == atendimento.cliente_id).one()
        assert pedido.endereco_entrega == "Rua das Palmeiras, 120, Centro"


class TestHistoricoERecomendacao:
    def test_ultimo_pedido_vem_do_banco(self, ana_identificada, llama, db):
        ultimo = repositorio.historico_cliente(db, ana_identificada.cliente_id, limite=1)[0]
        resposta = ana_identificada.responder("o que eu pedi da última vez?")
        assert resposta.startswith("Seu último pedido foi em")
        assert ultimo.itens[0].produto.nome in resposta
        assert llama.chamadas == []

    def test_entende_sem_interrogacao(self, ana_identificada, llama):
        # o whisper nem sempre coloca o ponto de interrogacao
        assert "Seu último pedido" in ana_identificada.responder("qual foi meu último pedido")
        assert llama.chamadas == []

    def test_lista_os_ultimos_pedidos(self, ana_identificada):
        assert "Seus últimos 3 pedidos" in ana_identificada.responder("quais foram meus pedidos anteriores?")

    def test_pedido_novo_aparece_no_historico(self, ana_identificada, llama):
        llama.entende([item("Pizza Portuguesa")])
        ana_identificada.responder("uma pizza portuguesa grande no pix")
        ana_identificada.responder("é só isso")
        ana_identificada.responder("sim, pode confirmar")
        assert "1 Pizza Portuguesa" in ana_identificada.responder("o que eu pedi da última vez?")

    def test_consultar_historico_nao_mexe_no_carrinho(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        ana_identificada.responder("o que eu pedi da última vez?")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]

    def test_cliente_novo_nao_tem_historico(self, atendimento):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("sim")
        assert "ainda não tem pedidos" in atendimento.responder("o que eu pedi da última vez?")

    def test_sem_conta_nao_mostra_historico(self, atendimento, llama):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("não")
        assert "Sem uma conta" in atendimento.responder("o que eu pedi da última vez?")
        assert llama.chamadas == []

    def test_recomenda_o_favorito_do_cliente(self, ana_identificada, llama):
        resposta = ana_identificada.responder("o que você me recomenda?")
        assert "Você costuma pedir Pizza de Calabresa" in resposta
        assert llama.chamadas == []

    def test_cada_cliente_ve_o_proprio_favorito(self, atendimento):
        atendimento.responder(seed.gerar_cpf(seed.CLIENTES[1][3]))
        resposta = atendimento.responder("o que você me recomenda?")
        assert "Pizza de Frango com Catupiry" in resposta
        assert "Calabresa" not in resposta

    def test_recomenda_dentro_da_categoria(self, ana_identificada):
        resposta = ana_identificada.responder("qual bebida você recomenda?")
        assert "Pizza" not in resposta

    def test_o_de_sempre_sugere_e_nao_compra(self, ana_identificada):
        resposta = ana_identificada.responder("quero o de sempre")
        assert "Pizza de Calabresa" in resposta
        assert ana_identificada.carrinho == []

    def test_cliente_novo_recebe_os_mais_pedidos_da_casa(self, atendimento, db):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("sim")
        campeao = repositorio.itens_mais_pedidos_da_casa(db, 1)[0][0]
        resposta = atendimento.responder("o que você recomenda?")
        assert "mais pedidos da casa" in resposta
        assert campeao.nome in resposta

    def test_sem_conta_tambem_recebe_sugestao_real(self, atendimento, llama):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("não")
        assert "mais pedidos da casa" in atendimento.responder("o que você recomenda?")
        assert llama.chamadas == []


class TestFurosDoHistoricoERecomendacao:
    @pytest.mark.parametrize("fala", [
        "não sei o que pedir", "estou em dúvida", "qual é a mais pedida?", "qual a melhor pizza?",
        "o que eu mais pedi?", "me dá uma indicação", "o que vocês têm de bom?",
    ])
    def test_duvida_vira_recomendacao_sem_o_llama(self, ana_identificada, llama, fala):
        assert "Pizza de Calabresa" in ana_identificada.responder(fala)
        assert llama.chamadas == []

    def test_refrigerante_recomenda_bebida(self, ana_identificada):
        assert "Pizza" not in ana_identificada.responder("qual refrigerante você recomenda?")

    def test_mais_pedida_da_casa_nao_usa_o_favorito(self, ana_identificada):
        assert "da casa" in ana_identificada.responder("qual é a mais pedida da casa?")

    def test_aceitar_a_sugestao_anota_o_produto(self, ana_identificada, llama):
        ana_identificada.responder("o que você me recomenda?")
        llama.entende([item("Pizza de Calabresa")])
        ana_identificada.responder("quero essa")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 1)]

    def test_sim_responde_a_pergunta_da_sugestao(self, ana_identificada):
        assert ana_identificada.responder("o que você me recomenda?").endswith("Quer pedir?")
        ana_identificada.responder("sim")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 1)]

    @pytest.mark.parametrize("fala", ["não", "não, obrigado", "agora não"])
    def test_recusar_a_sugestao_nao_fecha_nada(self, ana_identificada, fala):
        ana_identificada.responder("o que você me recomenda?")
        assert ana_identificada.responder(fala) == "Tudo bem. O que vai querer?"
        assert ana_identificada.carrinho == []
        assert ana_identificada.etapa == "identificado"

    def test_duas_sugestoes_pergunta_qual(self, atendimento):
        _cadastrar_ate_confirmar(atendimento)
        atendimento.responder("sim")
        atendimento.responder("o que você recomenda?")
        assert atendimento.responder("quero essa").startswith("Qual você quer")
        assert atendimento.carrinho == []

    def test_a_sugestao_vale_so_para_a_proxima_fala(self, ana_identificada, llama):
        ana_identificada.responder("o que você me recomenda?")
        ana_identificada.responder("quanto custa a margherita?")
        llama.entende([])
        ana_identificada.responder("quero essa")
        assert ana_identificada.carrinho == []

    def test_o_que_eu_pedi_ate_agora_olha_o_carrinho(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        assert "Até agora anotei 1 Pizza Margherita" in ana_identificada.responder("o que eu pedi até agora?")

    def test_o_que_eu_pedi_com_carrinho_nao_fala_do_passado(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        assert "Até agora anotei" in ana_identificada.responder("o que foi que eu pedi?")

    def test_ultima_vez_com_carrinho_continua_no_historico(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        assert "Seu último pedido" in ana_identificada.responder("o que eu pedi da última vez?")

    def test_reclamar_le_o_pedido_atual(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        resposta = ana_identificada.responder("esse não é o que eu pedi")
        assert "Até agora anotei" in resposta
        assert "O que você quer mudar?" in resposta

    def test_reclamar_sem_carrinho_nao_fala_do_historico(self, ana_identificada):
        assert "Ainda não anotei" in ana_identificada.responder("não foi isso que eu pedi")

    def test_fechar_meu_pedido_nao_vira_consulta(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita grande no pix")
        assert "Seu pedido ficou assim" in ana_identificada.responder("pode fechar meu pedido")

    def test_sem_vendas_nao_sugere_agua_para_sobremesa(self, ana_identificada, monkeypatch):
        monkeypatch.setattr(repositorio, "itens_mais_pedidos_do_cliente", lambda *a, **k: [])
        monkeypatch.setattr(repositorio, "itens_mais_pedidos_da_casa", lambda *a, **k: [])
        resposta = ana_identificada.responder("qual sobremesa você recomenda?")
        assert "Mousse" in resposta or "Pudim" in resposta

    def test_sem_vendas_sugere_pizza_salgada(self, ana_identificada, monkeypatch):
        monkeypatch.setattr(repositorio, "itens_mais_pedidos_do_cliente", lambda *a, **k: [])
        monkeypatch.setattr(repositorio, "itens_mais_pedidos_da_casa", lambda *a, **k: [])
        assert "Pizza" in ana_identificada.responder("o que você recomenda?")

    def test_pedido_antigo_sem_itens_nao_fala_frase_quebrada(self, ana_identificada, monkeypatch):
        pedido = SimpleNamespace(itens=[], total=Decimal("0"), criado_em=datetime.now(timezone.utc))
        monkeypatch.setattr(repositorio, "historico_cliente", lambda *a, **k: [pedido])
        assert "sem itens registrados" in ana_identificada.responder("o que eu pedi da última vez?")

    def test_banco_fora_do_ar_nao_derruba_a_conversa(self, ana_identificada, monkeypatch):
        def quebra(*a, **k):
            raise OperationalError("select", {}, Exception("banco caiu"))
        monkeypatch.setattr(repositorio, "historico_cliente", quebra)
        assert "problema para consultar" in ana_identificada.responder("o que eu pedi da última vez?")


class TestFurosDoLogin:
    def test_cpf_ditado_com_pausa(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        assert "Entendi 5 números" in atendimento.responder(cpf_da_ana[:5])
        assert "Ana" in atendimento.responder(cpf_da_ana[5:])
        assert atendimento.etapa == "identificado"

    def test_cpf_em_tres_pedacos(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder(cpf_da_ana[:3])
        atendimento.responder(cpf_da_ana[3:7])
        atendimento.responder(cpf_da_ana[7:])
        assert atendimento.etapa == "identificado"

    def test_pedaco_errado_nao_contamina_a_proxima_tentativa(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder("111")
        atendimento.responder("22233397")
        atendimento.responder(cpf_da_ana)
        assert atendimento.etapa == "identificado"

    def test_palavra_um_junto_do_cpf_nao_vira_digito(self, atendimento, cpf_da_ana):
        atendimento.responder("meu cpf é {}, um abraço".format(cpf_da_ana))
        assert atendimento.etapa == "identificado"

    def test_cpf_com_telefone_na_mesma_fala(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder("cpf {} e telefone 19998124477".format(cpf_da_ana))
        assert atendimento.etapa == "identificado"

    @pytest.mark.parametrize("fala", [
        "não quero falar meu cpf", "não tenho cpf", "prefiro não informar", "não vou dar meu cpf",
    ])
    def test_recusar_o_cpf_nao_prende_a_pessoa(self, atendimento, fala):
        atendimento.responder("oi")
        assert "dúvidas sobre o cardápio" in atendimento.responder(fala)
        assert atendimento.etapa == "sem_cadastro"

    def test_tres_erros_de_cpf_oferecem_saida(self, atendimento):
        atendimento.responder("oi")
        atendimento.responder("111.222.333-97")
        atendimento.responder("111.222.333-97")
        assert atendimento.etapa == "aguardando_cpf"
        assert "Não consegui confirmar" in atendimento.responder("111.222.333-97")
        assert atendimento.etapa == "sem_cadastro"

    def test_sem_conta_pode_voltar_a_informar_o_cpf(self, atendimento, llama, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder("não quero falar meu cpf")
        assert "CPF" in atendimento.responder("agora quero fazer um pedido")
        atendimento.responder(cpf_da_ana)
        assert atendimento.etapa == "identificado"
        assert llama.chamadas == []

    def test_sem_conta_pode_falar_o_cpf_direto(self, atendimento, cpf_da_ana):
        atendimento.responder("oi")
        atendimento.responder("não tenho cpf")
        atendimento.responder(cpf_da_ana)
        assert atendimento.etapa == "identificado"

    def test_cpf_novo_depois_do_nao_encontrei(self, atendimento, cpf_da_ana):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("meu cpf é " + cpf_da_ana)
        assert atendimento.etapa == "identificado"
        assert atendimento.cadastro == {}

    def test_errei_o_cpf_volta_para_a_pergunta(self, atendimento):
        atendimento.responder(CPF_NOVO)
        assert "CPF novamente" in atendimento.responder("não, errei o número")
        assert atendimento.etapa == "aguardando_cpf"
        assert atendimento.cadastro == {}

    @pytest.mark.parametrize("fala", ["não sou eu", "não sou a Ana", "esse não é meu cadastro", "cpf errado"])
    def test_nao_sou_eu_desfaz_o_login(self, ana_identificada, fala):
        assert "Desculpe pelo engano" in ana_identificada.responder(fala)
        assert ana_identificada.cliente_id is None
        assert ana_identificada.nome is None
        assert ana_identificada.endereco_do_cadastro is None
        assert ana_identificada.etapa == "aguardando_cpf"

    def test_nao_sou_eu_apaga_o_carrinho_e_limpa_a_tela(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        ana_identificada.responder("uma margherita")
        resultado = ana_identificada.responder_com_eventos("não sou eu")
        assert ana_identificada.carrinho == []
        assert resultado["eventos"][0]["cliente"]["nome"] is None
        assert resultado["eventos"][0]["itens"] == []
        assert resultado["eventos"][0]["endereco_entrega"] is None

    def test_depois_do_engano_nao_ve_o_historico_da_outra_pessoa(self, ana_identificada):
        ana_identificada.responder("não sou eu")
        assert "preciso do seu CPF" in ana_identificada.responder("o que eu pedi da última vez?")

    def test_pergunta_antes_do_cpf_explica_o_motivo(self, atendimento):
        atendimento.responder("oi")
        assert "preciso do seu CPF" in atendimento.responder("o que eu pedi da última vez?")

    def test_pergunta_no_cadastro_nao_vira_nome(self, atendimento):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        assert "Qual é o seu nome" in atendimento.responder("o que você recomenda?")
        assert atendimento.etapa == "aguardando_nome"
        assert "nome" not in atendimento.cadastro

    def test_pergunta_no_cadastro_nao_vira_endereco(self, atendimento):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder("João da Silva")
        atendimento.responder("19 99812 4477")
        atendimento.responder("o que eu pedi da última vez?")
        assert atendimento.etapa == "aguardando_endereco"

    @pytest.mark.parametrize("fala", ["sim", "ok", "não"])
    def test_resposta_solta_nao_vira_nome(self, atendimento, fala):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder(fala)
        assert atendimento.etapa == "aguardando_nome"

    @pytest.mark.parametrize("etapas", [1, 2, 3, 4])
    def test_desistir_no_meio_do_cadastro_nao_grava(self, atendimento, db, etapas):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        for fala in ["João da Silva", "19 99812 4477", "Rua das Palmeiras, 120"][:etapas - 1]:
            atendimento.responder(fala)
        assert "cancelei o cadastro" in atendimento.responder("desisti")
        assert atendimento.etapa == "sem_cadastro"
        assert repositorio.buscar_cliente_por_cpf(db, CPF_NOVO) is None

    def test_rua_cancela_continua_sendo_endereco(self, atendimento):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder("João da Silva")
        atendimento.responder("19 99812 4477")
        atendimento.responder("Rua Cancela, 10")
        assert atendimento.etapa == "confirmando_cadastro"


class TestQuandoOModeloEChamado:
    @pytest.mark.parametrize("fala", [
        "uma margherita", "quero uma pizza de calabresa e duas coca-colas", "vou pagar no pix",
        "no débito", "quero uma pizza", "uma de chocolate com sushi",
    ])
    def test_fala_resolvida_pelo_codigo_nao_espera_o_modelo(self, ana_identificada, llama, fala):
        ana_identificada.responder(fala)
        assert llama.chamadas == []

    def test_pedido_inteiro_funciona_com_o_ollama_fora_do_ar(self, ana_identificada, db):
        def indisponivel(*args, **kwargs):
            raise TimeoutError("Ollama indisponível")
        ana_identificada._conversar = indisponivel
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma margherita grande e duas coca-colas de 2 litros")
        ana_identificada.responder("vou pagar no pix")
        assert "96 reais e 70 centavos" in ana_identificada.responder("é só isso")
        assert "confirmado" in ana_identificada.responder("sim, pode confirmar")
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1

    @pytest.mark.parametrize("fala, itens", [
        ("tire as cocas", [("Pizza Margherita", 1)]),
        ("tira a margherita", [("Coca-Cola", 2)]),
        ("tira uma coca", [("Pizza Margherita", 1), ("Coca-Cola", 1)]),
        ("na verdade são três cocas", [("Pizza Margherita", 1), ("Coca-Cola", 3)]),
    ])
    def test_correcao_entendida_nao_espera_o_modelo(self, ana_identificada, llama, fala, itens):
        ana_identificada.responder("uma margherita grande e duas coca-colas de 2 litros")
        ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == itens
        assert llama.chamadas == []

    def test_correcao_funciona_com_o_ollama_fora_do_ar(self, ana_identificada):
        def indisponivel(*args, **kwargs):
            raise TimeoutError("Ollama indisponível")
        ana_identificada._conversar = indisponivel
        ana_identificada.responder("uma margherita grande e duas coca-colas de 2 litros no pix")
        ana_identificada.responder("é só isso")
        resposta = ana_identificada.responder("não, tire as cocas")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]
        assert "Seu pedido ficou assim" in resposta and "66 reais e 90 centavos" in resposta

    def test_tirar_mais_do_que_tem_pergunta_e_nao_mexe(self, ana_identificada, llama):
        ana_identificada.responder("uma margherita grande e duas coca-colas de 2 litros")
        ana_identificada.responder("tira cinco cocas de 2 litros")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [
            ("Pizza Margherita", 1), ("Coca-Cola", 2)]
        assert llama.chamadas == []

    def test_tirar_o_que_nao_esta_no_pedido_avisa_sem_o_modelo(self, ana_identificada, llama):
        ana_identificada.responder("uma margherita")
        resposta = ana_identificada.responder("tira a coca")
        assert resposta.startswith("Coca-Cola não está no seu pedido.")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]
        assert llama.chamadas == []

    def test_aviso_de_item_fora_do_pedido_nao_prende_a_conversa(self, ana_identificada):
        ana_identificada.responder("uma margherita grande no pix")
        ana_identificada.responder("tira a coca")
        assert "Seu pedido ficou assim" in ana_identificada.responder("é só isso")

    def test_item_certo_depois_do_aviso_segue_normal(self, ana_identificada):
        ana_identificada.responder("uma margherita")
        ana_identificada.responder("tira a coca")
        assert "Anotei 1 Pudim" in ana_identificada.responder("um pudim")

    @pytest.mark.parametrize("fala, esperado", [
        ("a entrega é na rua das flores, 10", "rua das flores, 10"),
        ("entrega na Avenida Brasil, 500, por favor.", "Avenida Brasil, 500"),
        ("rua das flores, 10, vou pagar no pix", "rua das flores, 10"),
        ("pode entregar na travessa do sol 12", "travessa do sol 12"),
    ])
    def test_endereco_com_rua_sai_da_fala_sem_o_modelo(self, ana_identificada, llama, fala, esperado):
        resposta = ana_identificada.responder(fala)
        assert ana_identificada.endereco_entrega == esperado
        assert esperado in resposta
        assert llama.chamadas == []

    def test_endereco_novo_vai_no_resumo(self, ana_identificada):
        ana_identificada.responder("uma margherita grande no pix")
        ana_identificada.responder("a entrega é na rua das flores, 10")
        assert "rua das flores, 10" in ana_identificada.responder("é só isso")

    def test_endereco_sem_nome_de_rua_ainda_usa_o_modelo(self, ana_identificada, llama):
        ana_identificada.responder("a entrega é no meu trabalho")
        assert len(llama.chamadas) == 1

    def test_pergunta_pendente_nao_muda_a_quantidade_da_remocao(self, ana_identificada, llama):
        ana_identificada.responder("uma margherita grande e duas coca-colas de 2 litros")
        ana_identificada.responder("quero uma pizza")
        llama.entende([item("margherita")])
        ana_identificada.responder("tire as cocas")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza Margherita", 1)]

    def test_pergunta_pendente_ainda_vale_para_o_sabor(self, ana_identificada):
        ana_identificada.responder("quero duas pizzas")
        ana_identificada.responder("margherita")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza Margherita", 2)]

    def test_o_inicio_do_prompt_nao_muda_entre_as_falas(self, ana_identificada, llama):
        ana_identificada.responder("a entrega é no meu trabalho")
        ana_identificada.responder("uma margherita")
        ana_identificada.responder("a entrega é na casa da minha mãe")
        primeiro, segundo = (c[0]["content"] for c in llama.chamadas)
        cardapio = primeiro.index("Pedido atual:")
        assert primeiro[:cardapio] == segundo[:cardapio]
        assert "Cardápio:" in primeiro[:cardapio]


def _itens(atendimento):
    return [(i["produto"], i["quantidade"], i["tamanho"]) for i in atendimento.carrinho]


class TestTamanhoDaPizza:
    @pytest.mark.parametrize("fala, tamanho", [
        ("pizza de calabresa grande.", "grande"), ("uma pizza grande de calabresa", "grande"),
        ("quero uma calabresa média", "média"), ("uma pizza de calabresa de tamanho grande", "grande"),
        ("uma calabresa pequena", "pequena"), ("uma calabresa broto", "pequena"),
        ("uma pizza média de calabresa", "média"), ("uma calabresa tamanho médio", "média"),
    ])
    def test_tamanho_dito_junto_ja_entra_no_pedido(self, ana_identificada, llama, fala, tamanho):
        resposta = ana_identificada.responder(fala)
        assert resposta == "Anotei 1 Pizza de Calabresa {}. Quer algo mais?".format(tamanho)
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, tamanho)]
        assert llama.chamadas == []

    def test_preco_sai_do_tamanho(self, ana_identificada):
        ana_identificada.responder("uma calabresa média e uma calabresa pequena")
        assert [(i["tamanho"], i["preco"]) for i in ana_identificada.carrinho] == [
            ("média", Decimal("49.90")), ("pequena", Decimal("39.90"))]

    def test_sem_tamanho_o_atendente_pergunta(self, ana_identificada, llama):
        resposta = ana_identificada.responder("uma calabresa")
        assert resposta == "Anotei 1 Pizza de Calabresa. Qual o tamanho: pequena, média ou grande?"
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala, tamanho", [
        ("grande", "grande"), ("média", "média"), ("a pequena", "pequena"), ("pode ser grande", "grande"),
        ("tamanho médio", "média"), ("a calabresa é grande", "grande"), ("uma calabresa grande", "grande"),
    ])
    def test_resposta_da_pergunta_do_tamanho(self, ana_identificada, llama, fala, tamanho):
        ana_identificada.responder("uma calabresa")
        assert ana_identificada.responder(fala) == "Certo, 1 Pizza de Calabresa {}. Quer algo mais?".format(tamanho)
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, tamanho)]
        assert llama.chamadas == []

    def test_repetir_o_sabor_nao_vira_outra_pizza(self, ana_identificada):
        ana_identificada.responder("uma calabresa")
        assert "tamanho" in ana_identificada.responder("a calabresa")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, None)]

    def test_resposta_com_outro_produto_anota_os_dois(self, ana_identificada):
        ana_identificada.responder("uma calabresa")
        ana_identificada.responder("grande, e uma coca lata")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "Lata")]

    def test_dois_sabores_sem_tamanho_pergunta_um_de_cada_vez(self, ana_identificada):
        resposta = ana_identificada.responder("uma calabresa e uma margherita")
        assert resposta.endswith("Qual o tamanho da Pizza de Calabresa: pequena, média ou grande?")
        resposta = ana_identificada.responder("grande")
        assert resposta == ("Certo, 1 Pizza de Calabresa grande. "
                            "Qual o tamanho da Pizza Margherita: pequena, média ou grande?")
        ana_identificada.responder("média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Pizza Margherita", 1, "média")]

    def test_duas_iguais_com_tamanhos_diferentes(self, ana_identificada):
        ana_identificada.responder("duas calabresas")
        ana_identificada.responder("uma grande e uma média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]

    def test_tamanhos_que_nao_fecham_a_conta_perguntam_de_novo(self, ana_identificada):
        ana_identificada.responder("uma calabresa")
        assert "Quantas de cada tamanho" in ana_identificada.responder("grande e média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, None)]

    @pytest.mark.parametrize("fala", ["família", "gigante"])
    def test_tamanho_que_nao_existe_avisa(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa")
        resposta = ana_identificada.responder(fala)
        assert resposta == "Não temos esse tamanho. A Pizza de Calabresa pode ser pequena, média ou grande?"
        assert "Certo, 1 Pizza de Calabresa grande" in ana_identificada.responder("grande")

    def test_tamanho_familia_na_mesma_frase_tambem_avisa(self, ana_identificada):
        resposta = ana_identificada.responder("pizza de calabresa tamanho família")
        assert "Não temos esse tamanho" in resposta
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, None)]

    def test_nao_fecha_sem_o_tamanho_e_le_o_resumo_depois(self, ana_identificada, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa no pix")
        resposta = ana_identificada.responder("é só isso")
        assert resposta == "Antes de fechar, qual o tamanho da Pizza de Calabresa: pequena, média ou grande?"
        assert ana_identificada.etapa == "identificado"
        assert "Seu pedido ficou assim: 1 Pizza de Calabresa média" in ana_identificada.responder("média")
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_resumo_e_pedido_gravado_tem_o_tamanho(self, ana_identificada, db):
        ana_identificada.responder("uma calabresa média no pix")
        resumo = ana_identificada.responder("é só isso")
        assert "1 Pizza de Calabresa média" in resumo
        assert "49 reais e 90 centavos" in resumo
        assert "confirmado" in ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert [(i.produto.nome, i.tamanho.nome, i.preco_unitario) for i in pedido.itens] == [
            ("Pizza de Calabresa", "média", Decimal("49.90"))]

    def test_mais_uma_igual_herda_o_tamanho(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("mais uma calabresa")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "grande")]

    def test_tirar_so_a_grande(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma calabresa média")
        ana_identificada.responder("tira a calabresa grande")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média")]

    def test_mudar_o_tamanho_depois(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert "Ajustei para 1 Pizza de Calabresa média" in ana_identificada.responder("na verdade a calabresa é média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média")]

    def test_troca_de_sabor_mantem_o_tamanho(self, ana_identificada):
        ana_identificada.responder("uma calabresa média")
        ana_identificada.responder("troque a calabresa por uma margherita")
        assert _itens(ana_identificada) == [("Pizza Margherita", 1, "média")]

    def test_troca_de_bebida_por_pizza_pergunta_o_tamanho(self, ana_identificada):
        ana_identificada.responder("uma coca de 2 litros")
        resposta = ana_identificada.responder("troque a coca por uma margherita")
        assert "Qual o tamanho da Pizza Margherita" in resposta
        assert _itens(ana_identificada) == [("Pizza Margherita", 1, None)]

    def test_agua_e_suco_tem_tamanho_unico(self, ana_identificada):
        assert ana_identificada.responder("um suco de laranja") == "Anotei 1 Suco de Laranja 1 Litro. Quer algo mais?"
        assert _itens(ana_identificada) == [("Suco de Laranja 1 Litro", 1, None)]

    def test_quantidade_e_mantida(self, ana_identificada):
        ana_identificada.responder("duas pizzas grandes de calabresa e uma coca-cola de 2 litros")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "grande"), ("Coca-Cola", 1, "2 Litros")]

    def test_sabor_vago_com_tamanho_ainda_pergunta_o_sabor(self, ana_identificada):
        resposta = ana_identificada.responder("quero uma pizza grande")
        assert "sabor" in resposta
        assert ana_identificada.carrinho == []

    @pytest.mark.parametrize("fala", ["quais tamanhos vocês têm?", "tem pizza grande?", "qual o tamanho da pizza?"])
    def test_pergunta_sobre_tamanho_responde_com_o_banco(self, ana_identificada, llama, fala):
        assert ana_identificada.responder(fala) == (
            "As pizzas podem ser pequena, com 4 fatias, média, com 6 fatias e grande, com 8 fatias. "
            "Os refrigerantes vêm em lata, 600 ml ou 2 litros.")
        assert llama.chamadas == []

    def test_pergunta_de_tamanho_no_meio_repete_a_pergunta_pendente(self, ana_identificada):
        ana_identificada.responder("uma calabresa")
        resposta = ana_identificada.responder("quais tamanhos vocês têm?")
        assert resposta.endswith("Qual o tamanho: pequena, média ou grande?")

    def test_so_o_tamanho_pede_o_produto(self, ana_identificada):
        assert "produto" in ana_identificada.responder("grande")
        assert ana_identificada.carrinho == []

    def test_rua_com_nome_de_tamanho_continua_igual(self, ana_identificada):
        ana_identificada.responder("a entrega é na Rua Grande, 10")
        assert ana_identificada.endereco_entrega == "Rua Grande, 10"

    def test_preco_com_tamanho_responde_o_preco_dele(self, ana_identificada, llama):
        assert "64 reais e 90 centavos" in ana_identificada.responder("quanto custa a pizza de calabresa grande?")
        assert ana_identificada.responder("quanto custa a calabresa média?") == (
            "A Pizza de Calabresa média custa 49 reais e 90 centavos.")
        assert llama.chamadas == []

    def test_preco_sem_tamanho_fala_os_tres(self, ana_identificada):
        assert ana_identificada.responder("quanto custa a calabresa?") == (
            "A Pizza de Calabresa custa 64 reais e 90 centavos a grande, 49 reais e 90 centavos a média "
            "e 39 reais e 90 centavos a pequena.")

    def test_preco_do_refrigerante_por_tamanho(self, ana_identificada):
        assert ana_identificada.responder("quanto custa a coca?") == (
            "A Coca-Cola custa 14 reais e 90 centavos a 2 litros, 8 reais a 600 ml e 6 reais a lata.")
        assert ana_identificada.responder("quanto custa a coca lata?") == "A Coca-Cola Lata custa 6 reais."

    def test_preco_de_agua_continua_um_so(self, ana_identificada):
        assert ana_identificada.responder("quanto custa a água mineral?") == "A Água Mineral 500ml custa 5 reais."

    def test_modelo_recebe_os_tamanhos_no_prompt(self, ana_identificada, llama):
        ana_identificada.responder("a entrega é no meu trabalho")
        prompt = llama.chamadas[0][0]["content"]
        assert "Tamanhos de pizza: pequena (4 fatias" in prompt


class TestErrosDeTranscricaoNosNomes:
    @pytest.mark.parametrize("fala, produto", [
        ("Pizza de calabresia", "Pizza de Calabresa"),
        ("uma margarita", "Pizza Margherita"),
        ("uma pizza de muçarela", "Pizza de Mussarela"),
        ("uma pizza portugesa", "Pizza Portuguesa"),
        ("uma pizza de peperoni", "Pizza de Pepperoni"),
    ])
    def test_nome_com_letra_errada_acha_o_produto(self, ana_identificada, llama, fala, produto):
        ana_identificada.responder(fala)
        assert [i["produto"] for i in ana_identificada.carrinho] == [produto]
        assert llama.chamadas == []

    def test_quanto_nao_vira_quatro_queijos(self, ana_identificada):
        resposta = ana_identificada.responder("quanto custa a margherita?")
        assert "Quatro Queijos" not in resposta
        assert "66 reais e 90 centavos" in resposta

    def test_produto_que_nao_existe_continua_recusado(self, ana_identificada):
        assert "Não temos" in ana_identificada.responder("uma pizza de sushi")
        assert ana_identificada.carrinho == []


class TestSaudacao:
    @pytest.mark.parametrize("hora, periodo", [
        (5, "bom dia"), (11, "bom dia"), (12, "boa tarde"), (17, "boa tarde"), (18, "boa noite"), (2, "boa noite"),
    ])
    def test_saudacao_usa_o_periodo_do_dia(self, atendimento, monkeypatch, hora, periodo):
        class Relogio:
            @staticmethod
            def now():
                return SimpleNamespace(hour=hora)
        monkeypatch.setattr("atendimento.datetime", Relogio)
        fala = atendimento.saudacao()
        assert fala.startswith("Olá, {}! Seja bem-vindo à pizzaria.".format(periodo))
        assert "CPF" in fala
        assert atendimento.etapa == "aguardando_cpf"

    def test_cpf_logo_depois_da_saudacao(self, atendimento, cpf_da_ana):
        atendimento.saudacao()
        atendimento.responder(cpf_da_ana)
        assert atendimento.etapa == "identificado"

    def test_responder_oi_nao_conta_como_erro_de_cpf(self, atendimento):
        atendimento.saudacao()
        for fala in ("oi", "olá, tudo bem?", "boa tarde", "oi", "alô"):
            assert "CPF" in atendimento.responder(fala)
        assert atendimento.etapa == "aguardando_cpf"


class TestMargemDeErroNaFala:
    @pytest.mark.parametrize("fala", [
        "me vê uma calabresa", "me dá uma pizza de calabresa", "traz uma calabresa pra mim",
        "vou querer uma calabresa", "eu vou querer uma pizza de calabresa", "vou de calabresa",
        "pode ser uma calabresa", "boa noite, quero uma calabresa", "então, uma calabresa",
        "ah, quero uma calabresa", "hoje vou querer uma calabresa",
    ])
    def test_jeitos_de_pedir(self, ana_identificada, llama, fala):
        ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 1)]
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala, produto", [
        ("pizza de mozarela", "Pizza de Mussarela"), ("pizza de muzzarela", "Pizza de Mussarela"),
        ("coca 2 litros", "Coca-Cola"),
    ])
    def test_grafias_e_volume(self, ana_identificada, fala, produto):
        ana_identificada.responder(fala)
        assert [i["produto"] for i in ana_identificada.carrinho] == [produto]

    def test_com_uma_coca_sao_dois_itens(self, ana_identificada):
        ana_identificada.responder("uma calabresa com uma coca de 2 litros")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza de Calabresa", "Coca-Cola"]

    def test_sem_cebola_continua_observacao(self, ana_identificada):
        ana_identificada.responder("uma calabresa sem cebola")
        assert ana_identificada.carrinho[0]["observacao"] == "sem cebola"
        assert len(ana_identificada.carrinho) == 1

    @pytest.mark.parametrize("fala", ["no pics", "no piques", "pics"])
    def test_pix_mal_transcrito(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder(fala)
        assert ana_identificada.pagamento == "pix"

    @pytest.mark.parametrize("fala", [
        "é isso", "é isso aí", "fecha o pedido", "fechar", "finaliza", "acabou", "mais nada", "nada mais",
        "não quero mais nada", "só isso, obrigado", "era isso", "por enquanto é só", "tá bom assim", "é só",
    ])
    def test_jeitos_de_fechar(self, ana_identificada, llama, fala):
        ana_identificada.responder("uma calabresa grande no pix")
        assert "Seu pedido ficou assim" in ana_identificada.responder(fala)
        assert ana_identificada.etapa == "confirmando_pedido"
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala", [
        "sim, pode", "pode", "pode sim", "confirma", "confirmado", "isso", "é isso", "tá certo", "está certo",
        "certo", "tudo certo", "claro", "com certeza", "beleza", "fechado", "perfeito", "aham", "uhum",
        "sim, por favor", "tá bom",
    ])
    def test_jeitos_de_confirmar(self, ana_identificada, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa grande no pix")
        ana_identificada.responder("é só isso")
        assert "confirmado" in ana_identificada.responder(fala)
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1

    @pytest.mark.parametrize("fala", ["sim?", "não", "sim, mas tira a calabresa", "pode ser que sim?", "espera", "calma aí"])
    def test_nao_confirma_com_duvida_ou_ressalva(self, ana_identificada, llama, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa grande no pix")
        ana_identificada.responder("é só isso")
        ana_identificada.responder(fala)
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_produto_que_nao_existe_com_prefixo_novo_continua_recusado(self, ana_identificada):
        ana_identificada.responder("me vê uma pizza de sushi")
        assert ana_identificada.carrinho == []


class TestDicaParaOWhisper:
    def test_com_o_cliente_identificado_a_dica_traz_o_cardapio(self, ana_identificada):
        dica = ana_identificada.dica_de_transcricao()
        assert "Coca-Cola" in dica and "Lata, 600 ml ou 2 litros" in dica
        # "Pizza de" em todo sabor estourava o limite de dica do whisper
        assert "Calabresa" in dica and "Pizza de Calabresa" not in dica
        assert "Pequena, média ou grande" in dica

    def test_produto_desativado_fica_fora(self, ana_identificada):
        assert "Escarola" not in ana_identificada.dica_de_transcricao()

    def test_dica_nao_tem_comando_que_o_ruido_possa_repetir(self, ana_identificada):
        dica = ana_identificada.dica_de_transcricao().lower()
        assert not any(c in dica for c in ("só isso", "confirm", "fechar", "pode ser"))

    def test_cpf_e_cadastro_nao_recebem_dica(self, atendimento):
        assert atendimento.dica_de_transcricao() is None
        atendimento.saudacao()
        assert atendimento.dica_de_transcricao() is None
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        assert atendimento.dica_de_transcricao() is None

    def test_banco_fora_do_ar_nao_impede_a_transcricao(self, ana_identificada, monkeypatch):
        def quebra(*a, **k):
            raise OperationalError("select", {}, Exception("banco caiu"))
        monkeypatch.setattr(repositorio, "listar_cardapio", quebra)
        assert ana_identificada.dica_de_transcricao() is None

    def test_ruido_inventado_e_descartado(self):
        segmentos = [SimpleNamespace(text=" uma coca-cola", no_speech_prob=0.1),
                     SimpleNamespace(text=" é só isso", no_speech_prob=0.84)]
        assert juntar_segmentos(segmentos) == " uma coca-cola"

    def test_produto_nao_entendido_tem_frase_natural(self, ana_identificada):
        resposta = ana_identificada.responder("eu quero uma pizza de calabreza e uma foca escona")
        assert "1 unidades" not in resposta
        assert "Não entendi um dos produtos" in resposta
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza de Calabresa"]


class TestNumeroNoNomeDoProduto:
    @pytest.mark.parametrize("fala, quantidade", [
        ("Pizza 4 Queijos", 1), ("uma pizza 4 queijos", 1), ("duas pizzas 4 queijos", 2), ("2 pizzas 4 queijos", 2),
        ("pizza quatro queijos", 1),
    ])
    def test_quatro_queijos_nao_vira_quatro_pizzas(self, ana_identificada, fala, quantidade):
        ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [
            ("Pizza Quatro Queijos", quantidade)]

    def test_quatro_calabresas_continua_sendo_quatro(self, ana_identificada):
        ana_identificada.responder("4 calabresas")
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 4)]

    def test_preco_da_4_queijos_nao_cai_em_outra_conta(self, ana_identificada):
        assert "78 reais e 90 centavos" in ana_identificada.responder("quanto custa a pizza 4 queijos?")


class TestQuerAlgoMais:
    def test_depois_de_anotar_pergunta_se_quer_mais(self, ana_identificada):
        assert ana_identificada.responder("uma coca de 2 litros") == "Anotei 1 Coca-Cola 2 Litros. Quer algo mais?"

    @pytest.mark.parametrize("fala", ["não", "não, obrigado", "não quero", "agora não"])
    def test_nao_fecha_o_pedido(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa grande no pix")
        assert "Seu pedido ficou assim" in ana_identificada.responder(fala)

    def test_sim_pergunta_o_que_mais(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert ana_identificada.responder("sim") == "Claro! O que mais vai querer?"
        assert len(ana_identificada.carrinho) == 1

    def test_pagamento_e_confirmado_na_fala(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert ana_identificada.responder("vou pagar no pix") == "Certo, pagamento no Pix. Quer algo mais?"

    def test_depois_do_pagamento_vai_direto_para_o_resumo(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert "Como você vai pagar" in ana_identificada.responder("não")
        assert "Seu pedido ficou assim" in ana_identificada.responder("no pix")
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_nao_com_pergunta_pendente_nao_fecha(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande no pix")
        ana_identificada.responder("quero uma pizza")
        ana_identificada.responder("não")
        assert ana_identificada.etapa == "identificado"

    def test_nao_sem_nada_no_pedido_pergunta_o_que_quer(self, ana_identificada):
        assert "O que vai querer" in ana_identificada.responder("não")


class TestConversaNatural:
    def test_repetir_o_ultimo_pedido(self, ana_identificada, db):
        ultimo = repositorio.historico_cliente(db, ana_identificada.cliente_id, limite=1)[0]
        assert ana_identificada.responder("o que eu pedi da última vez?").endswith("Quer pedir de novo?")
        ana_identificada.responder("sim")
        anotado = {(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho}
        assert anotado == {(i.produto.nome, i.quantidade) for i in ultimo.itens}

    def test_recusar_repetir_nao_anota_nada(self, ana_identificada):
        ana_identificada.responder("o que eu pedi da última vez?")
        assert ana_identificada.responder("não") == "Tudo bem. O que vai querer?"
        assert ana_identificada.carrinho == []

    def test_cardapio_fala_as_categorias(self, ana_identificada, llama):
        resposta = ana_identificada.responder("qual é o cardápio?")
        assert resposta.startswith("Temos pizzas doces, pizzas salgadas")
        assert "reais" not in resposta
        assert llama.chamadas == []

    def test_cardapio_completo_continua_listando_tudo(self, ana_identificada):
        resposta = ana_identificada.responder("me fala o cardápio completo")
        assert "Coca-Cola: 14 reais e 90 centavos" in resposta

    @pytest.mark.parametrize("fala, esperado, fora", [
        ("quais bebidas vocês têm?", "Coca-Cola", "Pizza"),
        ("quais são as sobremesas?", "Pudim de Leite", "Coca"),
        ("quais pizzas doces tem?", "Pizza de Brigadeiro", "Pizza Margherita"),
    ])
    def test_categoria_lista_sem_chamar_o_modelo(self, ana_identificada, llama, fala, esperado, fora):
        resposta = ana_identificada.responder(fala)
        assert esperado in resposta and fora not in resposta
        assert llama.chamadas == []

    def test_pergunta_sobre_um_produto_nao_lista_a_categoria(self, ana_identificada):
        assert "Pizza de Brigadeiro" not in ana_identificada.responder("a pizza de mussarela tem azeitona?")

    @pytest.mark.parametrize("fala, inicio", [
        ("quanto custa a margherita?", "A Pizza Margherita custa"),
        ("quanto custa o guaraná?", "O Guaraná custa"),
        ("quanto custa a coca?", "A Coca-Cola custa"),
        ("quanto custa o pudim?", "O Pudim de Leite custa"),
    ])
    def test_preco_usa_o_artigo_certo(self, ana_identificada, fala, inicio):
        assert ana_identificada.responder(fala).startswith(inicio)

    def test_fim_do_pedido(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande no pix")
        ana_identificada.responder("é só isso")
        fala = ana_identificada.responder("sim")
        assert fala.endswith("confirmado! Obrigado, Ana, e bom apetite!")


class TestNuncaFicaPreso:
    @pytest.mark.parametrize("fala", [
        "Não, não quero mais nada.", "não, só isso", "sim, é só isso", "nada mais, obrigado", "Quero pagar.",
        "pode cobrar", "quero fechar", "fecha a conta",
    ])
    def test_frases_de_fim_fecham_o_pedido(self, ana_identificada, llama, fala):
        ana_identificada.responder("um pudim de leite no pix")
        assert "Seu pedido ficou assim" in ana_identificada.responder(fala)
        assert llama.chamadas == []

    def test_quero_pagar_no_pix_ja_registra_e_fecha(self, ana_identificada):
        ana_identificada.responder("um pudim de leite")
        assert "pagamento no Pix" in ana_identificada.responder("quero pagar no pix")
        assert ana_identificada.pagamento == "pix"

    def test_item_com_fim_na_mesma_frase_ainda_anota(self, ana_identificada):
        ana_identificada.responder("um pudim de leite no pix")
        resposta = ana_identificada.responder("uma coca de 2 litros e só isso")
        assert "Seu pedido ficou assim" in resposta
        assert "Coca-Cola" in resposta

    def test_produto_que_nao_existe_nao_prende_as_proximas_falas(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert "Não temos" in ana_identificada.responder("uma pizza de sushi")
        assert "Anotei 1 Coca-Cola" in ana_identificada.responder("uma coca de 2 litros")
        assert "pagamento no Pix" in ana_identificada.responder("no pix")

    def test_nao_depois_de_produto_inexistente_segue_a_conversa(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("uma pizza de sushi")
        assert ana_identificada.responder("não") == "Tudo bem. Quer algo mais?"
        assert "Como você vai pagar" in ana_identificada.responder("não")

    def test_fala_que_nao_entende_nao_e_repetida_de_volta(self, ana_identificada):
        resposta = ana_identificada.responder("isso aqui não tem nada a ver com pizza hoje")
        assert "isso aqui" not in resposta

    def test_desistir_do_sabor_nao_trava(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande no pix")
        ana_identificada.responder("quero uma pizza")
        assert "Seu pedido ficou assim" in ana_identificada.responder("não quero mais nada")
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza de Calabresa"]


class TestEcoDoWhisper:
    @pytest.mark.parametrize("ouvido, esperado", [
        ("pudim de leite, pudim de leite", "pudim de leite"),
        ("Um pudim de leite. Um pudim de leite.", "Um pudim de leite."),
        ("uma coca-cola uma coca-cola uma coca-cola", "uma coca-cola"),
        ("Um pudim. Um pudim de leite.", "Um pudim de leite."),
    ])
    def test_trecho_repetido_vira_um_so(self, ouvido, esperado):
        assert juntar_segmentos([SimpleNamespace(text=ouvido, no_speech_prob=0.1)]) == esperado

    @pytest.mark.parametrize("ouvido", ["111.111.111-11", "111 222 333 96", "1 1 1 2 2 2 3 3 3 9 6", "19 99999 9999"])
    def test_numero_repetido_nao_e_eco(self, ouvido):
        assert juntar_segmentos([SimpleNamespace(text=ouvido, no_speech_prob=0.1)]) == ouvido

    def test_duas_pizzas_diferentes_continuam_iguais(self):
        fala = "uma calabresa e uma margherita"
        assert juntar_segmentos([SimpleNamespace(text=fala, no_speech_prob=0.1)]) == fala

    def test_eco_nao_cobra_duas_vezes(self, ana_identificada):
        texto = juntar_segmentos([SimpleNamespace(text="pudim de leite, pudim de leite", no_speech_prob=0.1)])
        ana_identificada.responder(texto)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [("Pudim de Leite", 1)]


class TestNaoESoIsso:
    @pytest.mark.parametrize("fala", ["não é só isso", "não só isso"])
    def test_sem_virgula_pede_mais(self, ana_identificada, fala):
        ana_identificada.responder("um pudim de leite no pix")
        ana_identificada.responder(fala)
        assert ana_identificada.etapa == "identificado"

    def test_com_virgula_encerra(self, ana_identificada):
        ana_identificada.responder("um pudim de leite no pix")
        assert "Seu pedido ficou assim" in ana_identificada.responder("não, é só isso")


class TestConfirmacaoComErroDoWhisper:
    def _no_resumo(self, atendimento):
        atendimento.responder("um pudim de leite no pix")
        atendimento.responder("é só isso")
        assert atendimento.etapa == "confirmando_pedido"

    @pytest.mark.parametrize("fala", ["Podia.", "Poisito.", "Positivo", "positiva", "confirmou", "fechou", "pois não", "ótimo"])
    def test_confirmacao_mal_transcrita_grava(self, ana_identificada, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._no_resumo(ana_identificada)
        assert "confirmado" in ana_identificada.responder(fala)
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes + 1

    @pytest.mark.parametrize("fala", ["blorp", "xyz abc", "agora", "cancelo", "confira", "espera"])
    def test_palavra_solta_pergunta_de_novo_sem_gravar(self, ana_identificada, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        self._no_resumo(ana_identificada)
        resposta = ana_identificada.responder(fala)
        assert resposta.startswith("Desculpe, não entendi. Posso confirmar")
        assert "cardápio" not in resposta
        assert ana_identificada.etapa == "confirmando_pedido"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_depois_de_nao_entender_ainda_da_para_confirmar(self, ana_identificada):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("blorp")
        assert "confirmado" in ana_identificada.responder("sim")

    @pytest.mark.parametrize("fala, esperado", [("no débito", "cartao_debito"), ("em dinheiro", "dinheiro")])
    def test_mudar_o_pagamento_no_resumo_continua_funcionando(self, ana_identificada, fala, esperado):
        self._no_resumo(ana_identificada)
        ana_identificada.responder(fala)
        assert ana_identificada.pagamento == esperado

    def test_acrescentar_item_no_resumo_continua_funcionando(self, ana_identificada):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("uma coca de 2 litros")
        assert "Coca-Cola" in [i["produto"] for i in ana_identificada.carrinho]

    def test_nao_continua_voltando_para_o_pedido(self, ana_identificada):
        self._no_resumo(ana_identificada)
        assert ana_identificada.responder("não") == "Tudo bem. O que você quer mudar?"

    def test_parecida_nao_vale_fora_da_confirmacao(self, ana_identificada):
        assert parece_confirmacao("poisito")
        assert not parece_confirmacao("poisito?")
        assert not parece_confirmacao("poisito agora")


class TestPagamentoJuntoDoItem:
    @pytest.mark.parametrize("fala, pagamento", [
        ("uma coca em dinheiro", "dinheiro"), ("uma coca no dinheiro", "dinheiro"), ("uma coca com pix", "pix"),
        ("uma coca pix", "pix"), ("uma coca no crédito", "cartao_credito"),
        ("uma coca no cartão de débito", "cartao_debito"), ("uma coca, vou pagar no pix", "pix"),
    ])
    def test_item_e_pagamento_na_mesma_frase(self, ana_identificada, llama, fala, pagamento):
        ana_identificada.responder(fala)
        item_anotado = ana_identificada.carrinho[0]
        assert (item_anotado["produto"], item_anotado["quantidade"]) == ("Coca-Cola", 1)
        assert item_anotado["observacao"] is None
        assert ana_identificada.pagamento == pagamento
        assert llama.chamadas == []

    def test_cartao_sem_dizer_qual_pergunta(self, ana_identificada):
        assert "Crédito ou débito" in ana_identificada.responder("uma coca de 2 litros no cartão")
        assert len(ana_identificada.carrinho) == 1

    def test_observacao_continua_com_o_pagamento_junto(self, ana_identificada):
        ana_identificada.responder("uma calabresa sem cebola no pix")
        assert ana_identificada.carrinho[0]["observacao"] == "sem cebola"
        assert ana_identificada.pagamento == "pix"


class TestMudarEndereco:
    def _no_resumo(self, atendimento):
        atendimento.responder("uma coca de 2 litros no pix")
        atendimento.responder("é só isso")
        assert atendimento.etapa == "confirmando_pedido"

    @pytest.mark.parametrize("fala", [
        "quero mudar o endereço", "Quero mudar com o endereço.", "muda o endereço", "o endereço está errado",
        "quero outro endereço", "troca o endereço",
    ])
    def test_no_resumo_pergunta_o_novo(self, ana_identificada, llama, fala):
        self._no_resumo(ana_identificada)
        assert ana_identificada.responder(fala) == "Claro! Qual é o novo endereço?"
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala, esperado", [
        ("rua das flores, 10", "rua das flores, 10"), ("a entrega é na Avenida Brasil, 500", "Avenida Brasil, 500"),
        ("Condomínio Vila Verde, casa 3", "Condomínio Vila Verde, casa 3"),
    ])
    def test_proxima_fala_vira_o_endereco_e_volta_ao_resumo(self, ana_identificada, fala, esperado):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("quero mudar o endereço")
        resposta = ana_identificada.responder(fala)
        assert "Seu pedido ficou assim" in resposta and esperado in resposta
        assert ana_identificada.etapa == "confirmando_pedido"

    def test_endereco_novo_vai_no_pedido_e_nao_muda_o_cadastro(self, ana_identificada, db):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("quero mudar o endereço")
        ana_identificada.responder("rua das flores, 10")
        ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.endereco_entrega == "rua das flores, 10"
        assert pedido.cliente.endereco != "rua das flores, 10"

    def test_antes_de_fechar_continua_pedindo_mais(self, ana_identificada):
        ana_identificada.responder("uma coca de 2 litros")
        ana_identificada.responder("quero mudar o endereço")
        assert ana_identificada.responder("rua das flores, 10").endswith("Quer algo mais?")

    def test_frase_com_a_rua_muda_direto(self, ana_identificada):
        ana_identificada.responder("uma coca de 2 litros")
        ana_identificada.responder("troca o endereço para a rua das flores, 10")
        assert ana_identificada.endereco_entrega == "rua das flores, 10"
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Coca-Cola"]

    def test_desistir_mantem_o_endereco(self, ana_identificada):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("quero mudar o endereço")
        resposta = ana_identificada.responder("não")
        assert "Rua Barao de Jaguara" in resposta
        assert ana_identificada.endereco_entrega is None

    def test_endereco_curto_pede_de_novo(self, ana_identificada):
        self._no_resumo(ana_identificada)
        ana_identificada.responder("quero mudar o endereço")
        assert "Não entendi o endereço" in ana_identificada.responder("oi")
        assert "Seu pedido ficou assim" in ana_identificada.responder("rua das flores, 10")

    def test_dica_do_cardapio_sai_enquanto_ouve_o_endereco(self, ana_identificada):
        ana_identificada.responder("quero mudar o endereço")
        assert ana_identificada.dica_de_transcricao() is None


class TestCpfNaLegenda:
    @pytest.mark.parametrize("fala", ["123.456.789-09", "meu cpf é 123 456 789 09", "um dois três quatro cinco seis"])
    def test_cpf_nao_aparece_na_etapa_do_cpf(self, atendimento, fala):
        atendimento.saudacao()
        assert atendimento.texto_para_tela(fala) == "CPF informado"

    def test_cumprimento_continua_aparecendo(self, atendimento):
        atendimento.saudacao()
        assert atendimento.texto_para_tela("oi, tudo bem?") == "oi, tudo bem?"

    def test_depois_do_login_a_fala_continua_normal(self, ana_identificada):
        fala = "2 pizzas de calabresa e 1 coca-cola 2 litros"
        assert ana_identificada.texto_para_tela(fala) == fala

    def test_cpf_dito_mais_tarde_tambem_some(self, ana_identificada):
        assert "123" not in ana_identificada.texto_para_tela("meu cpf é 123.456.789-09")

    def test_telefone_do_cadastro_aparece(self, atendimento):
        atendimento.responder(CPF_NOVO)
        atendimento.responder("sim")
        atendimento.responder("João da Silva")
        assert atendimento.texto_para_tela("19 99812 4477") == "19 99812 4477"


class TestAcentosDoCardapio:
    @pytest.mark.parametrize("fala, produto", [
        ("um guaraná", "Guaraná"), ("um guarana", "Guaraná"),
        ("uma água mineral", "Água Mineral 500ml"), ("uma agua mineral", "Água Mineral 500ml"),
        ("uma água com gás", "Água com Gás 500ml"), ("uma agua com gas", "Água com Gás 500ml"),
        ("um mousse de maracujá", "Mousse de Maracujá"),
    ])
    def test_com_e_sem_acento_acham_o_produto(self, ana_identificada, fala, produto):
        ana_identificada.responder(fala)
        assert [i["produto"] for i in ana_identificada.carrinho] == [produto]

    def test_so_agua_pergunta_com_ou_sem_gas(self, ana_identificada):
        resposta = ana_identificada.responder("uma água")
        assert "Água com Gás 500ml" in resposta and "Água Mineral 500ml" in resposta
        assert ana_identificada.carrinho == []


class TestRespostaDaAmbiguidade:
    @pytest.mark.parametrize("resposta, produto", [
        ("com gás", "Água com Gás 500ml"), ("sem gás", "Água Mineral 500ml"), ("a mineral", "Água Mineral 500ml"),
        ("a com gás", "Água com Gás 500ml"),
    ])
    def test_agua_com_ou_sem_gas(self, ana_identificada, llama, resposta, produto):
        ana_identificada.responder("duas águas")
        assert ana_identificada.responder(resposta) == "Anotei 2 {}. Quer algo mais?".format(produto)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [(produto, 2)]
        assert llama.chamadas == []

    def test_borda_pelo_recheio(self, ana_identificada):
        ana_identificada.responder("quero borda")
        assert ana_identificada.responder("catupiry") == "Anotei 1 Borda de Catupiry. Quer algo mais?"

    def test_resposta_que_serve_pras_duas_nao_escolhe(self, ana_identificada):
        ana_identificada.responder("uma água")
        ana_identificada.responder("500ml")
        assert ana_identificada.carrinho == []


class TestTamanhoDoRefrigerante:
    @pytest.mark.parametrize("fala, tamanho", [
        ("uma coca lata", "Lata"), ("uma coca de lata", "Lata"), ("uma coca latinha", "Lata"),
        ("uma coca em lata", "Lata"), ("uma coca 600", "600 ml"), ("uma coca de 600 ml", "600 ml"),
        ("uma coca 600ml", "600 ml"), ("uma coca de seiscentos", "600 ml"), ("uma coca de 2 litros", "2 Litros"),
        ("uma coca de dois litros", "2 Litros"),
    ])
    def test_tamanho_dito_junto(self, ana_identificada, llama, fala, tamanho):
        assert ana_identificada.responder(fala) == "Anotei 1 Coca-Cola {}. Quer algo mais?".format(tamanho)
        assert _itens(ana_identificada) == [("Coca-Cola", 1, tamanho)]
        assert llama.chamadas == []

    def test_sem_tamanho_pergunta_as_opcoes_de_refrigerante(self, ana_identificada):
        assert ana_identificada.responder("um guaraná") == (
            "Anotei 1 Guaraná. Qual o tamanho: lata, 600 ml ou 2 litros?")
        assert ana_identificada.responder("lata") == "Certo, 1 Guaraná Lata. Quer algo mais?"

    def test_pergunta_usa_o_artigo_do_produto(self, ana_identificada):
        resposta = ana_identificada.responder("uma calabresa grande e um guaraná e uma coca")
        assert resposta.endswith("Qual o tamanho do Guaraná: lata, 600 ml ou 2 litros?")
        assert ana_identificada.responder("600").endswith("Qual o tamanho da Coca-Cola: lata, 600 ml ou 2 litros?")

    def test_preco_sai_do_tamanho(self, ana_identificada):
        ana_identificada.responder("duas cocas lata e uma coca de 600")
        assert [(i["tamanho"], i["quantidade"], i["preco"]) for i in ana_identificada.carrinho] == [
            ("Lata", 2, Decimal("6.00")), ("600 ml", 1, Decimal("8.00"))]

    def test_tamanho_de_pizza_nao_serve_pra_refrigerante(self, ana_identificada):
        ana_identificada.responder("uma coca")
        assert ana_identificada.responder("grande") == (
            "Não temos esse tamanho. A Coca-Cola pode ser lata, 600 ml ou 2 litros?")
        assert _itens(ana_identificada) == [("Coca-Cola", 1, None)]

    def test_lata_nao_serve_pra_pizza(self, ana_identificada):
        ana_identificada.responder("uma calabresa")
        assert "Não temos esse tamanho" in ana_identificada.responder("lata")

    def test_duas_latas_e_uma_de_dois_litros(self, ana_identificada):
        ana_identificada.responder("três cocas")
        ana_identificada.responder("duas latas e uma de 2 litros")
        assert _itens(ana_identificada) == [("Coca-Cola", 2, "Lata"), ("Coca-Cola", 1, "2 Litros")]

    def test_resumo_e_pedido_gravado_tem_o_tamanho(self, ana_identificada, db):
        ana_identificada.responder("uma calabresa grande e duas cocas lata no pix")
        resumo = ana_identificada.responder("é só isso")
        assert "1 Pizza de Calabresa grande e 2 Coca-Cola Lata" in resumo
        assert "76 reais e 90 centavos" in resumo
        assert "confirmado" in ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert sorted((i.produto.nome, i.tamanho.nome, i.preco_unitario) for i in pedido.itens) == [
            ("Coca-Cola", "Lata", Decimal("6.00")), ("Pizza de Calabresa", "grande", Decimal("64.90"))]

    def test_troca_de_refrigerante_mantem_o_tamanho(self, ana_identificada):
        ana_identificada.responder("uma coca lata")
        ana_identificada.responder("troque a coca por um guaraná")
        assert _itens(ana_identificada) == [("Guaraná", 1, "Lata")]

    def test_tirar_so_a_lata(self, ana_identificada):
        ana_identificada.responder("uma coca lata e uma coca de 2 litros")
        ana_identificada.responder("tira a coca lata")
        assert _itens(ana_identificada) == [("Coca-Cola", 1, "2 Litros")]

    def test_quantidade_nao_vira_o_volume(self, ana_identificada):
        # "duas cocas de 2 litros": o 2 dos litros nao eh a quantidade
        ana_identificada.responder("três cocas de 2 litros")
        assert _itens(ana_identificada) == [("Coca-Cola", 3, "2 Litros")]


class TestTamanhoJuntoDoFechamento:
    def test_tamanho_pagamento_e_fim_na_mesma_fala(self, ana_identificada, llama):
        ana_identificada.responder("uma calabresa média e uma coca")
        resposta = ana_identificada.responder("lata, no pix, é só isso")
        assert resposta.startswith("Seu pedido ficou assim: 1 Pizza de Calabresa média e 1 Coca-Cola Lata.")
        assert "55 reais e 90 centavos" in resposta
        assert ana_identificada.etapa == "confirmando_pedido"
        assert llama.chamadas == []

    def test_tamanho_de_pizza_e_fim_na_mesma_fala(self, ana_identificada):
        ana_identificada.responder("uma calabresa no pix")
        assert "Seu pedido ficou assim: 1 Pizza de Calabresa grande" in ana_identificada.responder("grande, é só isso")


class TestConsultaSemProdutoCerto:
    @pytest.mark.parametrize("fala, falta", [
        ("quanto custa a pizza de sushi?", "pizza de sushi"),
        ("quais ingredientes da pizza de sushi?", "pizza de sushi"),
        ("quanto custa a água de coco?", "agua de coco"),
    ])
    def test_produto_que_nao_existe_nao_le_os_parecidos(self, ana_identificada, llama, fala, falta):
        resposta = ana_identificada.responder(fala)
        assert resposta == "Não temos {} no cardápio. Quer saber de outra opção?".format(falta)
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala", ["quanto custa a pizza?", "quanto custam as pizzas?",
                                      "qual o preço da pizza grande?"])
    def test_pergunta_generica_nao_le_o_cardapio_inteiro(self, ana_identificada, llama, fala):
        resposta = ana_identificada.responder(fala)
        assert resposta.startswith("Temos ") and resposta.endswith("opções de pizza. De qual você quer saber?")
        assert "reais" not in resposta
        assert llama.chamadas == []

    def test_categoria_pequena_lista_os_nomes(self, ana_identificada):
        resposta = ana_identificada.responder("quanto custa a pizza doce?")
        assert resposta.startswith("Temos 5 opções de pizza doce: ")
        assert "Pizza de Brigadeiro" in resposta and "Pizza de Calabresa" not in resposta

    @pytest.mark.parametrize("fala, trechos", [
        ("quanto custa a água?", ["A Água Mineral 500ml custa 5 reais.", "A Água com Gás 500ml custa"]),
        ("quanto custa a borda?", ["A Borda de Catupiry custa 12 reais.", "A Borda de Cheddar custa 12 reais."]),
        ("quanto custa a calabresa e a mussarela?", ["A Pizza de Calabresa custa", "A Pizza de Mussarela custa"]),
        ("quanto custa a pizza de frango?", ["A Pizza de Frango com Catupiry custa"]),
    ])
    def test_poucas_opcoes_continuam_com_o_preco(self, ana_identificada, fala, trechos):
        resposta = ana_identificada.responder(fala)
        assert all(trecho in resposta for trecho in trechos)


class TestJeitosDeTrocar:
    @pytest.mark.parametrize("fala", [
        "troca a calabresa por uma mussarela", "troca a calabresa por mussarela",
        "troca a calabresa pela mussarela", "não, troca a calabresa por uma mussarela",
        "na verdade troca a calabresa por uma mussarela", "substitui a calabresa pela mussarela",
    ])
    def test_troca_uma_por_uma_mantendo_o_tamanho(self, ana_identificada, llama, fala):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == [("Pizza de Mussarela", 1, "grande")]
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala", [
        "em vez da calabresa quero uma mussarela", "em vez da calabresa, uma mussarela",
        "no lugar da calabresa coloca uma mussarela", "ao invés da calabresa pode ser uma mussarela",
        "quero uma mussarela no lugar da calabresa", "me vê uma mussarela em vez da calabresa",
        "muda a calabresa pra mussarela", "muda a calabresa para uma mussarela",
    ])
    def test_outras_formas_de_troca_tiram_o_item_antigo(self, ana_identificada, llama, fala):
        # antes a mussarela entrava e a calabresa ficava: pedido com uma pizza a mais
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == [("Pizza de Mussarela", 1, "grande")]
        assert llama.chamadas == []

    def test_mude_continua_corrigindo_a_quantidade(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("mude para duas calabresas")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "grande")]

    def test_item_que_nao_esta_no_pedido_nao_e_trocado(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("em vez da portuguesa quero uma mussarela")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]
        assert ana_identificada.responder("deixa pra lá") == (
            "Tudo bem, mantive seu pedido como estava. Quer algo mais?")

    @pytest.mark.parametrize("fala, tamanho", [
        ("troca a calabresa grande por uma média", "média"), ("troca a calabresa por uma média", "média"),
        ("muda a calabresa pra pequena", "pequena"), ("muda o tamanho da calabresa pra média", "média"),
    ])
    def test_troca_so_de_tamanho_mantem_o_sabor(self, ana_identificada, llama, fala, tamanho):
        ana_identificada.responder("uma calabresa grande sem cebola")
        ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"], i["tamanho"], i["observacao"])
                for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 1, tamanho, "sem cebola")]
        assert ana_identificada.carrinho[0]["preco"] == {"média": Decimal("49.90"), "pequena": Decimal("39.90")}[tamanho]
        assert llama.chamadas == []

    def test_troca_de_volume_do_refrigerante(self, ana_identificada):
        ana_identificada.responder("uma coca lata")
        ana_identificada.responder("troca a coca lata por uma de 2 litros")
        assert _itens(ana_identificada) == [("Coca-Cola", 1, "2 Litros")]
        ana_identificada.responder("muda a coca pra 600")
        assert _itens(ana_identificada) == [("Coca-Cola", 1, "600 ml")]

    def test_uma_de_duas_muda_de_tamanho(self, ana_identificada):
        ana_identificada.responder("duas calabresas grandes")
        ana_identificada.responder("troca uma calabresa por uma média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]

    def test_no_plural_todas_mudam_e_no_singular_pergunta(self, ana_identificada):
        ana_identificada.responder("duas calabresas grandes")
        assert "Quantas unidades" in ana_identificada.responder("muda a calabresa pra pequena")
        ana_identificada.responder("cancela a troca")
        ana_identificada.responder("muda as calabresas pra pequena")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "pequena")]

    @pytest.mark.parametrize("pedido, fala, resposta", [
        ("uma coca lata", "muda a coca pra grande", "A Coca-Cola não tem esse tamanho. Pode ser lata, 600 ml ou 2 litros?"),
        ("um pudim", "muda o pudim pra grande", "O Pudim de Leite tem tamanho único."),
    ])
    def test_tamanho_que_nao_serve_nao_muda_nada(self, ana_identificada, pedido, fala, resposta):
        ana_identificada.responder(pedido)
        anterior = list(ana_identificada.carrinho)
        assert ana_identificada.responder(fala).startswith(resposta)
        assert ana_identificada.carrinho == anterior

    @pytest.mark.parametrize("fala", ["a calabresa é média", "quero a calabresa média", "a calabresa pode ser média"])
    def test_artigo_definido_muda_o_tamanho_da_pizza_anotada(self, ana_identificada, llama, fala):
        # antes entrava uma segunda calabresa e a grande continuava no pedido
        ana_identificada.responder("uma calabresa grande sem cebola")
        assert ana_identificada.responder(fala) == "Certo, 1 Pizza de Calabresa média (sem cebola). Quer algo mais?"
        assert [(i["produto"], i["quantidade"], i["tamanho"], i["observacao"])
                for i in ana_identificada.carrinho] == [("Pizza de Calabresa", 1, "média", "sem cebola")]
        assert llama.chamadas == []

    def test_no_plural_as_duas_mudam(self, ana_identificada):
        ana_identificada.responder("duas calabresas grandes")
        ana_identificada.responder("as calabresas são médias")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "média")]

    def test_refrigerante_tambem_muda_de_volume(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        ana_identificada.responder("a coca pode ser de 600")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "600 ml")]

    def test_repetir_o_mesmo_tamanho_nao_soma_outra(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("a calabresa é grande")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]

    @pytest.mark.parametrize("fala", ["uma calabresa média", "quero uma calabresa média",
                                      "mais uma calabresa média", "quero outra calabresa média"])
    def test_pedir_outra_continua_somando(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]

    def test_duas_do_mesmo_sabor_em_tamanhos_diferentes_nao_adivinha(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma calabresa média")
        anterior = list(ana_identificada.carrinho)
        ana_identificada.responder("a calabresa é pequena")
        assert ana_identificada.carrinho == anterior

    def test_nao_sem_virgula_continua_negando_a_troca(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("não troca a calabresa por uma mussarela")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]

    def test_saindo_mais_de_uma_a_quantidade_que_entra_e_perguntada(self, ana_identificada):
        ana_identificada.responder("duas calabresas grandes")
        resposta = ana_identificada.responder("troca duas calabresas por mussarela")
        assert "Quantas unidades de Pizza de Mussarela" in resposta
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 2, "grande")]

    def test_troca_na_confirmacao_le_o_resumo_novo(self, ana_identificada, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa grande no pix, é só isso")
        resposta = ana_identificada.responder("não, troca a calabresa por uma mussarela")
        assert resposta.startswith("Seu pedido ficou assim: 1 Pizza de Mussarela grande.")
        assert ana_identificada.etapa == "confirmando_pedido"
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes
        assert "confirmado" in ana_identificada.responder("sim")

    @pytest.mark.parametrize("fala", ["cancela a troca", "cancela", "deixa pra lá", "esquece", "deixa como está",
                                      "não precisa", "não quero mais trocar"])
    def test_cliente_sai_de_uma_troca_nao_entendida(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("troca a calabresa por uma pizza de sushi")
        assert ana_identificada._troca_pendente
        ana_identificada.responder(fala)
        assert not ana_identificada._troca_pendente
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]
        # e o pedido volta a andar
        assert ana_identificada.responder("é só isso").startswith("Como você vai pagar?")


class TestQuantidadeDivididaEmTamanhos:
    @pytest.mark.parametrize("fala, itens", [
        ("duas calabresas, uma grande e uma média",
         [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]),
        ("quero duas calabresas uma grande e uma média",
         [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]),
        ("três mussarelas, duas grandes e uma pequena",
         [("Pizza de Mussarela", 2, "grande"), ("Pizza de Mussarela", 1, "pequena")]),
        ("duas cocas, uma lata e uma de 2 litros", [("Coca-Cola", 1, "Lata"), ("Coca-Cola", 1, "2 Litros")]),
        ("duas calabresas, uma grande e uma média, e uma coca lata",
         [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média"), ("Coca-Cola", 1, "Lata")]),
    ])
    def test_cada_numero_leva_o_tamanho_dito_depois(self, ana_identificada, llama, fala, itens):
        # antes: "Não temos calabresas uma e uma no cardápio"
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == itens
        assert llama.chamadas == []

    def test_conta_que_nao_fecha_pergunta_e_aceita_a_resposta(self, ana_identificada):
        resposta = ana_identificada.responder("duas calabresas, uma grande e duas médias")
        assert resposta == "Anotei 2 Pizza de Calabresa. Quantas de cada tamanho? Por exemplo: uma grande e uma média."
        ana_identificada.responder("uma grande e uma média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Pizza de Calabresa", 1, "média")]


class TestMudaSoOTamanhoSemCitarProduto:
    @pytest.mark.parametrize("fala", ["muda pra média", "troca pra média", "pode ser média", "quero média",
                                      "muda o tamanho pra média"])
    def test_muda_o_unico_item_com_tamanho(self, ana_identificada, llama, fala):
        # antes: "Não temos muda pra no cardápio"
        ana_identificada.responder("uma calabresa grande sem cebola e um pudim")
        resposta = ana_identificada.responder(fala)
        assert resposta == "Certo, 1 Pizza de Calabresa média (sem cebola). Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média"), ("Pudim de Leite", 1, None)]
        assert llama.chamadas == []

    def test_refrigerante_muda_de_volume(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        ana_identificada.responder("muda pra 2 litros")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "2 Litros")]

    def test_dois_itens_possiveis_pergunta_qual(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma mussarela grande")
        resposta = ana_identificada.responder("muda pra média")
        assert resposta == "Qual item muda para média? Diga, por exemplo: a pizza de calabresa é média."
        ana_identificada.responder("a calabresa é média")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média"), ("Pizza de Mussarela", 1, "grande")]

    def test_nenhum_item_com_esse_tamanho(self, ana_identificada):
        ana_identificada.responder("uma coca lata")
        resposta = ana_identificada.responder("muda pra grande")
        assert resposta == "Nenhum item do seu pedido tem o tamanho grande. Quer algo mais?"
        assert _itens(ana_identificada) == [("Coca-Cola", 1, "Lata")]


class TestMudaAQuantidade:
    @pytest.mark.parametrize("fala, qtd", [
        ("altere a coca para duas", 2), ("muda a coca pra três", 3), ("deixa duas cocas", 2),
        ("muda a coca pra uma", 1), ("mude para duas", 2),
    ])
    def test_ajusta_a_quantidade_em_vez_de_somar(self, ana_identificada, llama, fala, qtd):
        # antes: "Não temos coca para duas no cardápio"
        ana_identificada.responder("três cocas lata" if qtd == 1 else "uma coca lata")
        resposta = ana_identificada.responder(fala)
        assert resposta == "Ajustei para {} Coca-Cola Lata. Quer algo mais?".format(qtd)
        assert _itens(ana_identificada) == [("Coca-Cola", qtd, "Lata")]
        assert llama.chamadas == []

    def test_sem_produto_com_dois_itens_pergunta_qual(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        resposta = ana_identificada.responder("muda pra duas")
        assert resposta == "Qual item muda para duas? Diga, por exemplo: muda a pizza de calabresa para duas."
        ana_identificada.responder("muda a coca para duas")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 2, "Lata")]

    def test_item_fora_do_pedido_nao_e_somado(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        resposta = ana_identificada.responder("muda a coca pra duas")
        assert resposta == "Coca-Cola não está no seu pedido. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]

    def test_pedido_vazio(self, ana_identificada):
        assert ana_identificada.responder("muda pra duas") == "Seu pedido ainda está vazio. O que vai querer?"


class TestObservacaoSemProduto:
    @pytest.mark.parametrize("fala, observacao", [
        ("sem cebola", "sem cebola"), ("pode ser sem cebola", "sem cebola"), ("sem cebola, por favor", "sem cebola"),
        ("com bastante orégano", "com bastante orégano"), ("não coloca cebola", "sem cebola"),
        ("tira a cebola", "sem cebola"), ("não coloca cebola na calabresa", "sem cebola"),
    ])
    def test_vai_pro_unico_item(self, ana_identificada, llama, fala, observacao):
        # antes: "Não temos sem cebola no cardápio"
        ana_identificada.responder("uma calabresa grande")
        resposta = ana_identificada.responder(fala)
        assert resposta == "Ajustei para 1 Pizza de Calabresa grande ({}). Quer algo mais?".format(observacao)
        assert ana_identificada.carrinho[0]["observacao"] == observacao
        assert llama.chamadas == []

    def test_dois_itens_pergunta_qual(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        resposta = ana_identificada.responder("sem cebola")
        assert resposta == "Qual item fica sem cebola? Diga, por exemplo: a pizza de calabresa sem cebola."
        assert all(i["observacao"] is None for i in ana_identificada.carrinho)

    def test_produto_fora_do_pedido(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        resposta = ana_identificada.responder("tira a cebola da mussarela")
        assert resposta == "Pizza de Mussarela não está no seu pedido. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]

    def test_soma_com_a_observacao_anterior(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande sem cebola")
        ana_identificada.responder("com bastante orégano")
        assert ana_identificada.carrinho[0]["observacao"] == "sem cebola e com bastante orégano"

    def test_mesmo_ingrediente_substitui(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande sem cebola")
        ana_identificada.responder("com cebola")
        assert ana_identificada.carrinho[0]["observacao"] == "com cebola"


class TestApelidoDoItem:
    @pytest.mark.parametrize("fala, resposta, itens", [
        ("a pizza sem cebola", "Ajustei para 1 Pizza de Calabresa grande (sem cebola). Quer algo mais?",
         [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "Lata")]),
        ("a pizza é média", "Certo, 1 Pizza de Calabresa média. Quer algo mais?",
         [("Pizza de Calabresa", 1, "média"), ("Coca-Cola", 1, "Lata")]),
        ("tira a pizza", "Tirei 1 Pizza de Calabresa grande. Quer algo mais?", [("Coca-Cola", 1, "Lata")]),
        ("tira a bebida", "Tirei 1 Coca-Cola Lata. Quer algo mais?", [("Pizza de Calabresa", 1, "grande")]),
        ("o refri pode ser de 2 litros", "Certo, 1 Coca-Cola 2 Litros. Quer algo mais?",
         [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "2 Litros")]),
        ("muda a pizza pra duas", "Ajustei para 2 Pizza de Calabresa grande. Quer algo mais?",
         [("Pizza de Calabresa", 2, "grande"), ("Coca-Cola", 1, "Lata")]),
    ])
    def test_o_tipo_aponta_o_unico_item_dele(self, ana_identificada, llama, fala, resposta, itens):
        # antes: "Claro! Qual sabor você quer?" e "tira a bebida" virava observação
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        assert ana_identificada.responder(fala) == resposta
        assert _itens(ana_identificada) == itens
        assert llama.chamadas == []

    def test_duas_pizzas_continua_perguntando(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma mussarela grande")
        assert ana_identificada.responder("a pizza sem cebola") == "Claro! Qual sabor você quer?"
        assert all(i["observacao"] is None for i in ana_identificada.carrinho)


class TestJeitosDeTirar:
    @pytest.mark.parametrize("fala", ["esquece a coca", "não quero mais a coca", "não coloca coca não",
                                      "muda a coca pra zero"])
    def test_tira_o_item(self, ana_identificada, llama, fala):
        # antes: "Não entendi" ou "Qual é a observação para Coca-Cola?"
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        assert ana_identificada.responder(fala) == "Tirei 1 Coca-Cola Lata. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]
        assert llama.chamadas == []

    def test_nao_quero_mais_uma_tira_so_uma(self, ana_identificada):
        ana_identificada.responder("duas cocas lata")
        ana_identificada.responder("não quero mais uma coca")
        assert _itens(ana_identificada) == [("Coca-Cola", 1, "Lata")]

    def test_tira_ingrediente_nao_tira_a_pizza(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        resposta = ana_identificada.responder("tira a cebola da calabresa")
        assert resposta == "Ajustei para 1 Pizza de Calabresa grande (sem cebola). Quer algo mais?"
        assert len(ana_identificada.carrinho) == 2

    def test_nao_coloca_o_que_nao_foi_pedido(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert ana_identificada.responder("não coloca coca não") == "Coca-Cola não está no seu pedido. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]


class TestFalaSemPedido:
    @pytest.mark.parametrize("fala, resposta", [
        ("oi", "Olá! O que vai querer?"),
        ("olá, boa noite", "Olá! O que vai querer?"),
        ("tudo bem?", "Olá! O que vai querer?"),
        ("quero pedir", "Claro! O que vai querer?"),
        ("quero fazer um pedido", "Claro! O que vai querer?"),
        ("gostaria de fazer um pedido", "Claro! O que vai querer?"),
        ("espera um pouco", "Sem pressa. Quando decidir, é só falar."),
        ("um momento", "Sem pressa. Quando decidir, é só falar."),
        ("deixa eu ver", "Sem pressa. Quando decidir, é só falar."),
        ("obrigado", "De nada! O que vai querer?"),
    ])
    def test_nao_culpa_o_cardapio(self, ana_identificada, llama, fala, resposta):
        assert ana_identificada.responder(fala) == resposta
        assert ana_identificada.carrinho == []
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala, resposta", [
        ("oi", "Olá! Qual o tamanho: pequena, média ou grande?"),
        ("obrigado", "De nada! Qual o tamanho: pequena, média ou grande?"),
        ("espera aí", "Sem pressa. Quando decidir, é só falar."),
    ])
    def test_pergunta_aberta_continua_valendo(self, ana_identificada, fala, resposta):
        ana_identificada.responder("uma calabresa")
        assert ana_identificada.responder(fala) == resposta
        # e a resposta do tamanho ainda eh aceita, sem "desculpe, nao entendi"
        assert ana_identificada.responder("grande") == "Certo, 1 Pizza de Calabresa grande. Quer algo mais?"

    def test_com_itens_pergunta_se_quer_mais(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        assert ana_identificada.responder("oi") == "Olá! Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]

    def test_produto_nao_entendido_nao_e_repetido_depois_do_cumprimento(self, ana_identificada):
        ana_identificada.responder("uma pizza de sushi")
        assert ana_identificada.responder("obrigado") == "De nada! O que vai querer?"

    @pytest.mark.parametrize("fala", ["oi, quero uma calabresa grande", "boa noite, me vê uma calabresa grande"])
    def test_cumprimento_junto_do_pedido_continua_pedindo(self, ana_identificada, fala):
        assert ana_identificada.responder(fala) == "Anotei 1 Pizza de Calabresa grande. Quer algo mais?"


class TestPerguntaSeTem:
    @pytest.mark.parametrize("fala, inicio", [
        ("tem pizza de calabresa?", "Temos, sim. A Pizza de Calabresa custa 64 reais e 90 centavos a grande"),
        ("tem calabresa?", "Temos, sim. A Pizza de Calabresa custa"),
        ("vocês têm coca?", "Temos, sim. A Coca-Cola custa 14 reais e 90 centavos a 2 litros"),
        ("vocês vendem pudim?", "Temos, sim. O Pudim de Leite custa 15 reais e 90 centavos."),
        ("tem pizza de frango?", "Temos, sim. A Pizza de Frango com Catupiry custa"),
    ])
    def test_produto_do_cardapio_responde_com_o_preco(self, ana_identificada, llama, fala, inicio):
        resposta = ana_identificada.responder(fala)
        assert resposta.startswith(inicio) and resposta.endswith("Quer pedir?")
        assert ana_identificada.carrinho == []
        assert llama.chamadas == []

    def test_o_sim_seguinte_pede_o_produto(self, ana_identificada):
        ana_identificada.responder("tem pizza de calabresa?")
        assert ana_identificada.responder("quero") == (
            "Anotei 1 Pizza de Calabresa. Qual o tamanho: pequena, média ou grande?")

    def test_o_nao_seguinte_nao_pede_nada(self, ana_identificada):
        ana_identificada.responder("tem pizza de calabresa?")
        ana_identificada.responder("não")
        assert ana_identificada.carrinho == []

    def test_produto_que_nao_existe_nao_lista_os_parecidos(self, ana_identificada, llama):
        assert ana_identificada.responder("tem pizza de sushi?") == (
            "Não temos pizza de sushi no cardápio. Quer saber de outra opção?")
        assert llama.chamadas == []

    def test_mais_de_um_produto_lista_as_opcoes(self, ana_identificada):
        assert ana_identificada.responder("tem água?") == (
            "Temos Água Mineral 500ml e Água com Gás 500ml. Quer saber o preço de alguma opção?")

    def test_categoria_continua_listando_os_sabores(self, ana_identificada):
        resposta = ana_identificada.responder("tem pizza doce?")
        assert "Pizza de Brigadeiro" in resposta and "Pizza de Calabresa" not in resposta

    def test_ingrediente_nao_e_pergunta_de_disponibilidade(self, ana_identificada):
        assert ana_identificada.responder("a calabresa tem cebola?") == (
            "Pizza de Calabresa: calabresa fatiada, cebola e azeitona preta.")


class TestPerguntaDoTotal:
    @pytest.mark.parametrize("fala", [
        "quanto ficou?", "quanto deu", "qual o total?", "quanto tá dando?", "quanto vai ficar?", "qual o valor?",
        "quanto é?", "quanto fica tudo?", "qual o valor do pedido?", "quanto eu vou pagar?", "quanto dá?",
        "qual é o total da conta?", "quanto ficou mesmo?",
    ])
    def test_total_sai_do_carrinho_sem_o_modelo(self, ana_identificada, llama, fala):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        resposta = ana_identificada.responder(fala)
        assert resposta == ("Até agora anotei 1 Pizza de Calabresa grande e 1 Coca-Cola Lata, "
                            "subtotal de 70 reais e 90 centavos. Quer algo mais?")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande"), ("Coca-Cola", 1, "Lata")]
        assert llama.chamadas == []

    def test_sem_itens_nao_inventa_total(self, ana_identificada, llama):
        assert ana_identificada.responder("quanto ficou?") == "Ainda não anotei nada neste pedido. O que vai querer?"
        assert llama.chamadas == []

    @pytest.mark.parametrize("fala, trecho", [
        ("quanto é a mussarela média?", "A Pizza de Mussarela média custa 44 reais e 90 centavos."),
        ("quanto fica a calabresa pequena?", "A Pizza de Calabresa pequena custa 39 reais e 90 centavos."),
        ("quanto custa a coca?", "A Coca-Cola custa"),
    ])
    def test_preco_de_um_produto_continua_sendo_o_do_produto(self, ana_identificada, fala, trecho):
        ana_identificada.responder("uma calabresa grande")
        assert ana_identificada.responder(fala).startswith(trecho)

    def test_total_perguntado_na_confirmacao_nao_grava(self, ana_identificada, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa grande no pix, é só isso")
        assert "subtotal de 64 reais e 90 centavos" in ana_identificada.responder("quanto ficou mesmo?")
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes


class TestVerbosDePedir:
    @pytest.mark.parametrize("fala", [
        "coloca uma calabresa grande", "bota uma calabresa grande", "põe uma calabresa grande",
        "adiciona uma calabresa grande", "acrescenta uma calabresa grande", "inclui uma calabresa grande",
        "anota aí uma calabresa grande", "pode colocar uma calabresa grande", "pode colocar uma calabresa grande?",
        "quero pedir uma calabresa grande", "gostaria de pedir uma calabresa grande",
    ])
    def test_jeitos_de_pedir_um_item(self, ana_identificada, llama, fala):
        assert ana_identificada.responder(fala) == "Anotei 1 Pizza de Calabresa grande. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]
        assert llama.chamadas == []

    def test_coloca_mais_uma_soma_na_que_ja_existe(self, ana_identificada):
        ana_identificada.responder("uma portuguesa grande")
        ana_identificada.responder("coloca mais uma portuguesa grande")
        assert _itens(ana_identificada) == [("Pizza Portuguesa", 2, "grande")]

    @pytest.mark.parametrize("fala", [
        "remove a coca", "exclui a coca", "cancela a coca", "pode tirar a coca", "pode tirar a coca?",
    ])
    def test_jeitos_de_tirar_um_item(self, ana_identificada, llama, fala):
        ana_identificada.responder("uma calabresa grande e uma coca lata")
        assert ana_identificada.responder(fala) == "Tirei 1 Coca-Cola Lata. Quer algo mais?"
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]
        assert llama.chamadas == []

    def test_verbo_nao_e_confundido_com_produto_parecido(self, ana_identificada):
        # "anota" ficava a uma letra de "fanta" e "cancela" de "canela"
        ana_identificada.responder("anota uma calabresa grande")
        ana_identificada.responder("cancela a calabresa")
        assert ana_identificada.carrinho == []

    def test_tirar_ingrediente_nao_tira_a_pizza(self, ana_identificada):
        ana_identificada.responder("uma calabresa grande")
        ana_identificada.responder("pode tirar a cebola da calabresa")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "grande")]


class TestEsvaziaOPedido:
    @pytest.mark.parametrize("fala", [
        "cancela o pedido", "pode cancelar o pedido, por favor", "tira tudo", "limpa o pedido",
        "não quero mais nada, cancela tudo", "quero começar de novo", "esquece o pedido", "cancela",
    ])
    def test_cliente_consegue_esvaziar_o_pedido(self, ana_identificada, llama, db, fala):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa média e uma coca lata no pix")
        resposta = ana_identificada.responder(fala)
        assert resposta == "Tudo bem, esvaziei o seu pedido. Nada foi registrado. O que vai querer?"
        assert ana_identificada.carrinho == [] and ana_identificada.pagamento is None
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes
        assert llama.chamadas == []
        # e a chamada segue: da pra pedir de novo
        ana_identificada.responder("uma mussarela grande")
        assert _itens(ana_identificada) == [("Pizza de Mussarela", 1, "grande")]

    def test_esvaziar_na_hora_da_confirmacao_nao_grava(self, ana_identificada, db):
        antes = _pedidos_da(db, ana_identificada.cliente_id)
        ana_identificada.responder("uma calabresa média no pix, é só isso")
        assert ana_identificada.etapa == "confirmando_pedido"
        assert "esvaziei" in ana_identificada.responder("cancela")
        assert ana_identificada.etapa == "identificado" and ana_identificada.carrinho == []
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes

    def test_sem_itens_avisa_que_ja_esta_vazio(self, ana_identificada):
        assert ana_identificada.responder("cancela o pedido") == "Seu pedido já está vazio. O que vai querer?"

    @pytest.mark.parametrize("fala", ["não cancela o pedido", "não precisa cancelar o pedido", "não tira tudo"])
    def test_pedido_negado_nao_esvazia(self, ana_identificada, fala):
        ana_identificada.responder("uma calabresa média")
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média")]

    def test_cancelar_a_troca_nao_esvazia_o_pedido(self, ana_identificada):
        ana_identificada.responder("uma calabresa média")
        ana_identificada.responder("troca a calabresa")
        ana_identificada.responder("cancele a troca")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média")]

    def test_tirar_um_item_continua_tirando_so_ele(self, ana_identificada):
        ana_identificada.responder("uma calabresa média e uma coca lata")
        ana_identificada.responder("tira a coca")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "média")]


@pytest.fixture
def tamanhos_novos(db):
    """tamanhos cadastrados depois do seed: nenhum deles esta escrito no codigo."""
    from models import Tamanho

    novos = [Tamanho(grupo="pizza", nome="gigante", fatias=12, desconto=Decimal("0")),
             Tamanho(grupo="refrigerante", nome="350 ml", desconto=Decimal("9.90"))]
    db.add_all(novos)
    db.commit()
    yield
    for tamanho in novos:
        db.delete(tamanho)
    db.commit()


class TestTamanhoCadastradoNoBanco:
    @pytest.mark.parametrize("fala, esperado, preco", [
        ("uma calabresa gigante", ("Pizza de Calabresa", 1, "gigante"), "64.90"),
        ("duas pizzas gigantes de calabresa", ("Pizza de Calabresa", 2, "gigante"), "64.90"),
        ("uma coca de 350 ml", ("Coca-Cola", 1, "350 ml"), "5.00"),
        ("uma coca 350ml", ("Coca-Cola", 1, "350 ml"), "5.00"),
    ])
    def test_tamanho_novo_e_entendido_na_fala(self, tamanhos_novos, ana_identificada, llama, fala, esperado, preco):
        ana_identificada.responder(fala)
        assert _itens(ana_identificada) == [esperado]
        assert ana_identificada.carrinho[0]["preco"] == Decimal(preco)
        assert llama.chamadas == []

    def test_tamanho_novo_e_oferecido_e_aceito_como_resposta(self, tamanhos_novos, ana_identificada):
        pergunta = ana_identificada.responder("uma calabresa")
        assert "gigante" in pergunta
        ana_identificada.responder("gigante")
        assert _itens(ana_identificada) == [("Pizza de Calabresa", 1, "gigante")]

    def test_tamanho_novo_so_vale_para_o_grupo_dele(self, tamanhos_novos, ana_identificada):
        ana_identificada.responder("uma coca gigante")
        assert all(i["tamanho"] != "gigante" for i in ana_identificada.carrinho)

    def test_tamanho_novo_entra_na_dica_do_whisper(self, tamanhos_novos, ana_identificada):
        dica = ana_identificada.dica_de_transcricao()
        assert "gigante" in dica and "350 ml" in dica
