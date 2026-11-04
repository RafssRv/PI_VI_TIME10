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
from interpretacao import extrair_digitos, extrair_nome, sim_ou_nao

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
        assert "sabor" in atendimento.responder("quero uma pizza")
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
        assert "continuar escolhendo" in resposta
        assert "pagar" not in resposta
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
        assert "Não encontrei pizza de sushi" in resposta
        assert [i["produto"] for i in ana_identificada.carrinho] == ["Pizza Margherita"]

    def test_produto_desativado_vira_aviso(self, ana_identificada, llama):
        llama.entende([item("Pizza de Escarola com Bacon")])
        assert "Não encontrei" in ana_identificada.responder("uma de escarola")
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
        assert "crédito ou de débito" in ana_identificada.responder("no cartão")
        assert ana_identificada.pagamento is None

    def test_pagamento_null_nao_apaga_o_anterior(self, ana_identificada, llama):
        llama.entende([item("margherita")])
        llama.entende([item("margherita"), item("coca cola")])
        ana_identificada.responder("margherita no pix")
        ana_identificada.responder("e uma coca")
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
        ana_identificada.responder("Uma margherita e uma água no pix, é só isso")

        def nao_deve_reconstruir_carrinho(*args, **kwargs):
            raise AssertionError("A troca explícita não precisa da interpretação do LLM")

        ana_identificada._conversar = nao_deve_reconstruir_carrinho
        resposta = ana_identificada.responder(fala)
        assert [(i["produto"], i["quantidade"]) for i in ana_identificada.carrinho] == [
            ("Pizza Margherita", 2)]
        assert "133 reais e 80 centavos" in resposta
        assert _pedidos_da(db, ana_identificada.cliente_id) == antes
        assert "registrado" in ana_identificada.responder("sim")
        pedido = (db.query(Pedido).filter(Pedido.cliente_id == ana_identificada.cliente_id)
                  .order_by(Pedido.id.desc()).first())
        assert pedido.total == Decimal("133.80")
        assert [(i.produto.nome, i.quantidade) for i in pedido.itens] == [("Pizza Margherita", 2)]

    def test_troca_parcial_preserva_resto_e_nao_transfere_observacao(self, ana_identificada, llama):
        llama.entende([item("margherita", 2, "sem tomate"), item("água mineral", 3)])
        ana_identificada.responder("Duas margheritas sem tomate e três águas no pix")
        resposta = ana_identificada.responder("Troque duas águas por uma margherita")
        assert [(i["produto"], i["quantidade"], i["observacao"])
                for i in ana_identificada.carrinho] == [
            ("Pizza Margherita", 2, "sem tomate"), ("Agua Mineral 500ml", 1, None),
            ("Pizza Margherita", 1, None)]
        assert "continuar escolhendo" in resposta
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
        resposta = ana_identificada.responder("Troque duas cocas por uma água")
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

    @pytest.mark.parametrize("ultima_fala", ["cancele a troca", "troque uma coca por uma água"])
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
        assert len(llama.chamadas) == 1
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
            ana_identificada.responder("uma margherita")
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
                ana_identificada.responder("não, tire as cocas")
        else:
            assert "repetir" in ana_identificada.responder("não, tire as cocas")

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

        assert "registrado" in ana_identificada.responder("sim")
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
        self._pedir_e_fechar(ana_identificada, llama, endereco="Rua Nova, 45, Cambuí",
                            texto="uma margherita e duas cocas no pix, entrega na Rua Nova, 45, Cambuí, é só isso")
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
        ana_identificada.responder("uma pizza portuguesa no pix")
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
        assert "você mais pede Pizza de Calabresa" in resposta
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

    def test_sim_solto_orienta_e_nao_compra(self, ana_identificada):
        ana_identificada.responder("o que você me recomenda?")
        assert "uma Pizza de Calabresa" in ana_identificada.responder("sim")
        assert ana_identificada.carrinho == []

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
        ana_identificada.responder("uma margherita no pix")
        assert "Vou confirmar" in ana_identificada.responder("pode fechar meu pedido")

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
