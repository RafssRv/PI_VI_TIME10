# roteiro da chamada: identifica o cliente pelo cpf (cadastra se ele nao tiver conta) e
# depois monta e grava o pedido.
# quem consulta e grava no banco eh sempre o codigo, chamando as funcoes do repositorio.
# o llama so entra depois q o cliente ta identificado: ele conversa e devolve um json com o
# q entendeu do pedido, o python confere tudo contra o cardapio, le o resumo pro cliente e so
# grava quando ele confirma. o modelo nunca encosta no banco (nada de sql escrito por ele).
#
# uma instancia por chamada (a rota de voz cria uma por websocket), pq ela guarda em q etapa
# a conversa ta e o q o cliente ja disse.

import logging
import re
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from agente.controle_pedido import ControlePedido, ErroPedido, ProdutoCardapio
from agente.intencao_pedido import (CONSULTA_HISTORICO, CONSULTA_PEDIDO_ATUAL, CONSULTA_RECOMENDACAO, FALAS_DE_FECHAR,
                                   FECHAR, RECLAMA_DO_PEDIDO, cardapio_completo, comando_negado, eh_consulta,
                                   interpretar, mencoes)

from sqlalchemy.exc import SQLAlchemyError

import repositorio
from interpretacao import (
    ESQUEMA_DO_PEDIDO, PEDIDO_DE_TROCA, _item_da_troca, _nome_na_troca, _normalizar,
    confirmacao_explicita, extrair_digitos, extrair_endereco, extrair_nome,
    interpretar_resposta, sim_ou_nao,
)

logger = logging.getLogger(__name__)

# depois de uma sugestao, essas falas apontam pro produto sugerido
ACEITES_DA_SUGESTAO = {
    "quero", "vou querer", "quero sim", "sim quero", "quero essa", "quero esse", "sim quero essa",
    "sim quero esse", "vou querer essa", "vou querer esse", "pode ser essa", "pode ser esse",
    "essa", "esse", "essa mesmo", "esse mesmo", "manda essa", "manda esse", "pode mandar",
}
# um "sim" solto nao compra nada (regra 12 do prompt), mas tambem nao pode ficar sem resposta
RESPOSTAS_VAGAS_A_SUGESTAO = {"sim", "pode ser", "ok", "claro", "isso", "beleza", "certo", "aham", "uhum",
                              "ta bom", "perfeito", "pode", "pode sim", "sim pode", "sim por favor"}
CUMPRIMENTO = re.compile(r"^(?:oi|ola|alo|opa|e ai|bom dia|boa tarde|boa noite|tudo bem|tudo bom)\b")
CORTESIA = re.compile(r"\b(?:obrigad[oa]|valeu|por favor|viu)\b")
SINONIMOS_DE_CATEGORIA = {"refrigerante": "bebida", "refri": "bebida", "suco": "bebida", "agua": "bebida"}
ENDERECO_NA_FALA = re.compile(r"\b(?:rua|avenida|av|travessa|alameda|estrada|rodovia)\b.*", re.IGNORECASE)
# o cardapio nao tem tamanhos: "pizza de calabresa grande" eh a calabresa, nao um produto desconhecido
TAMANHO_NA_FALA = re.compile(r"(?<!em )\b(?:(?:de |do |no )?tamanho )?(?:grande|m[eé]dia|m[eé]dio|pequena|pequeno|"
                             r"gigante|fam[ií]lia|broto)\b", re.IGNORECASE)
PERGUNTA_DE_TAMANHO = re.compile(r"\btamanhos?\b|\btem\b.*\b(?:grande|media|medio|pequena|pequeno|gigante|"
                                 r"familia|broto)\b")
FRASE_TAMANHO_UNICO = "Trabalhamos com tamanho único."
# o que vem depois do endereco na mesma frase: "rua x, 10, e so isso"
FIM_DO_ENDERECO = re.compile(r"[,.;]?\s*\b(?:[eé] s[oó] isso|s[oó] isso|por favor|pode fechar|pago|pagamento|"
                             r"vou pagar|no pix|em dinheiro|no cart[aã]o|no cr[eé]dito|no d[eé]bito)\b.*",
                             re.IGNORECASE)

TENTATIVAS_DE_CPF = 3
RECUSA_DE_CPF = re.compile(
    r"\bnao (?:quero|vou|posso|gostaria de) (?:falar|dar|informar|passar|dizer)\b|"
    r"\bnao tenho cpf\b|\bsem cpf\b|\bprefiro nao\b"
)
CPF_ERRADO = re.compile(r"\b(?:errei|errado|errada|outro cpf)\b|\bnao e (?:esse|meu|o meu) cpf\b")
NAO_SOU_EU = re.compile(
    r"\bnao sou (?:eu|a|o|essa|esse)\b|\bnao e (?:meu nome|meu cadastro|minha conta|meu cpf|o meu cpf)\b|"
    r"\b(?:cpf|conta|cadastro) errad[oa]\b|\boutra pessoa\b"
)
# so no comeco da fala, pra "Rua Cancela, 10" continuar sendo endereco
DESISTIU_DO_CADASTRO = re.compile(r"^(?:eu )?(?:desisti|desistir|deixa pra la|deixa para la|cancela|cancelar|"
                                  r"nao quero mais)\b")
VOLTAR_PARA_O_CPF = re.compile(r"\b(?:cpf|criar (?:uma )?conta|me cadastrar|cadastro|fazer (?:um )?pedido|"
                               r"quero pedir)\b")


def extrair_cpf(texto):
    # um numero inteiro de 11 digitos ganha das palavras: em "52998224725, um abraco" o "um" nao eh digito
    for trecho in re.finditer(r"\d(?:[\d.\-\s]*\d)?", texto or ""):
        digitos = re.sub(r"\D", "", trecho.group())
        if len(digitos) == 11:
            return digitos
    return extrair_digitos(texto)

FRASE_PEDE_CPF = "Para começar, me diga o seu CPF, por favor."
FRASE_ERRO_BANCO = "Tive um problema para consultar o sistema. Pode repetir, por favor?"
FRASE_PEDE_PAGAMENTO = "Como você vai pagar? Pix, dinheiro, cartão de crédito ou débito?"

PAGAMENTO_FALADO = {
    "pix": "no Pix",
    "dinheiro": "em dinheiro",
    "cartao_credito": "no cartão de crédito",
    "cartao_debito": "no cartão de débito",
}

def remover_tamanho(texto):
    """tira o tamanho da fala e diz se tinha algum. nao mexe no endereco: "Rua Grande, 10" fica igual."""
    endereco = ENDERECO_NA_FALA.search(texto)
    corte = endereco.start() if endereco else len(texto)
    limpo, quantos = TAMANHO_NA_FALA.subn("", texto[:corte])
    limpo = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s+", " ", limpo + texto[corte:])).strip()
    return limpo, quantos > 0


def _prompt_base():
    return (Path(__file__).parent / "agente" / "prompt_sistema.txt").read_text(encoding="utf-8")


def formatar_telefone(digitos):
    # pro piper ler em voz alta de um jeito q a pessoa reconheca o proprio numero
    if len(digitos) == 11:
        return "({}) {}-{}".format(digitos[:2], digitos[2:7], digitos[7:])
    return "({}) {}-{}".format(digitos[:2], digitos[2:6], digitos[6:])


def _formatar_preco(preco):
    return "R$ {:.2f}".format(preco).replace(".", ",")


def preco_falado(valor):
    # "R$ 92,80" o piper le esquisito, entao no resumo vai por extenso
    centavos_totais = int((Decimal(str(valor)) * 100).quantize(Decimal("1")))
    reais, centavos = divmod(centavos_totais, 100)
    texto = "{} {}".format(reais, "real" if reais == 1 else "reais")
    if centavos:
        texto += " e {} {}".format(centavos, "centavo" if centavos == 1 else "centavos")
    return texto


def _juntar(partes, conector="e"):
    # ["a", "b", "c"] -> "a, b e c"
    if len(partes) <= 1:
        return "".join(partes)
    return "{} {} {}".format(", ".join(partes[:-1]), conector, partes[-1])


class Atendimento:
    def __init__(self, abrir_sessao=None, conversar=None):
        self.id_chamada = uuid4().hex
        # os dois podem vir de fora pros testes: a sessao do banco de teste e um llama de mentira
        self._abrir_sessao = abrir_sessao
        self._conversar = conversar
        self.etapa = "inicio"
        self.cliente_id = None
        self.nome = None
        self.telefone = None
        self.endereco_do_cadastro = None
        self.cadastro = {}
        self.historico = []
        self._cpf_parcial = ""
        self._erros_de_cpf = 0
        self._comanda_desatualizada = False
        self._dica = None
        self.sessao_id = self.id_chamada
        self.turno_id = 0
        self.ultimo_rastro = None
        self._pedido_salvo = None
        self._limpar_pedido()

    def _limpar_pedido(self):
        # carrinho so tem item ja conferido no cardapio: {"produto": nome exato, "quantidade",
        # "preco", "observacao"}
        self.carrinho = []
        self.pagamento = None
        self.endereco_entrega = None
        self._controle = None
        self._token_resumo = None
        self._pendencia = None
        self._sugestoes = []
        self._troca_pendente = False
        self._pendencia_antes_da_troca = None
        self._duvida_item = None
        self._tentativas = 0
        self._ultima_pergunta = None
        self._referencia = None
        self._fechamento_solicitado = False

    def responder(self, texto):
        """recebe o q o cliente falou e devolve o q o atendente fala de volta."""
        etapas = {
            "inicio": self._inicio,
            "aguardando_cpf": self._receber_cpf,
            "oferecendo_cadastro": self._receber_aceite,
            "aguardando_nome": self._receber_nome,
            "aguardando_telefone": self._receber_telefone,
            "aguardando_endereco": self._receber_endereco,
            "confirmando_cadastro": self._receber_confirmacao,
            "identificado": self._montar_pedido,
            "confirmando_pedido": self._receber_confirmacao_do_pedido,
            "sem_cadastro": self._conversar_com_llm,
        }
        self.turno_id += 1
        rastrear = self.etapa in {"identificado", "confirmando_pedido", "sem_cadastro"}
        if rastrear:
            # Só o último turno fica em memória. O validador pode salvá-lo com dados fictícios.
            self.ultimo_rastro = {"sessao": self.sessao_id, "turno": self.turno_id,
                                  "turno_voz": getattr(self, "turno_voz", None),
                                  "transcricao": texto, "antes": deepcopy(self.carrinho)}
        try:
            resposta = etapas[self.etapa](texto)
            if rastrear:
                self.ultimo_rastro["resposta"] = resposta
            return resposta
        finally:
            if rastrear:
                self.ultimo_rastro["depois"] = deepcopy(self.carrinho)
                logger.info(
                    "chamada=%s turno=%s etapa=pedido carrinho_alterado=%s", self.id_chamada,
                    self.turno_id, self.ultimo_rastro["antes"] != self.carrinho)

    def responder_com_eventos(self, texto):
        """Devolve a fala e o estado da comanda, sem interpretar o texto da resposta."""
        salvo_anterior = self._pedido_salvo
        resposta = self.responder(texto)
        eventos = []
        if self._comanda_desatualizada:
            # quem disse "nao sou eu" nao pode continuar vendo os dados da outra pessoa na tela
            self._comanda_desatualizada = False
            eventos.append({"tipo": "pedido", **self._dados_do_pedido()})
        if self.cliente_id is not None:
            pedido = self._pedido_salvo or self._dados_do_pedido()
            eventos.append({"tipo": "pedido", **deepcopy(pedido)})
            if self._pedido_salvo is not None and self._pedido_salvo is not salvo_anterior:
                eventos.append({"tipo": "pedido_salvo", "pedido_id": pedido["pedido_id"],
                                "total": pedido["total"]})
        return {"texto": resposta, "eventos": eventos}

    def _dados_do_pedido(self):
        return {
            "pedido_id": None,
            "cliente": {"nome": self.nome, "telefone": self.telefone},
            "itens": [{"produto": i["produto"], "quantidade": i["quantidade"],
                       "preco_unitario": format(i["preco"], ".2f"),
                       "observacao": i["observacao"]} for i in self.carrinho],
            "total": format(sum((i["preco"] * i["quantidade"] for i in self.carrinho),
                                Decimal("0.00")), ".2f"),
            "forma_pagamento": self.pagamento,
            "endereco_entrega": self.endereco_entrega or self.endereco_do_cadastro,
        }

    def dica_de_transcricao(self):
        """
        o que o whisper deve esperar ouvir. so vale quando a fala eh sobre o cardapio: no cpf nao ajuda
        e em nome e endereco atrapalharia. nao colocar comandos aqui: testando, o modelo repetia o fim
        da dica quando so ouvia ruido, e "e so isso" fecharia o pedido sozinho.
        """
        if self.etapa not in {"identificado", "confirmando_pedido", "sem_cadastro"}:
            return None
        if self._dica is None:
            db = self._sessao()
            try:
                nomes = [p.nome for p in repositorio.listar_cardapio(db)]
            except Exception:
                logger.warning("chamada=%s etapa=dica_transcricao categoria=banco", self.id_chamada)
                return None
            finally:
                db.close()
            self._dica = ("Cardápio da pizzaria: {}. Pix, dinheiro, crédito e débito. "
                          "O cliente diz o pedido:").format(", ".join(nomes))
        return self._dica

    # --- banco ---

    def _sessao(self):
        if self._abrir_sessao is None:
            from database import SessionLocal
            self._abrir_sessao = SessionLocal
        return self._abrir_sessao()

    # --- identificacao ---

    def saudacao(self):
        """primeira fala da chamada. o cpf eh obrigatorio pra pedir, entao ja sai pedindo."""
        if self.etapa == "inicio":
            self.etapa = "aguardando_cpf"
        hora = datetime.now().hour
        periodo = "bom dia" if 5 <= hora < 12 else "boa tarde" if 12 <= hora < 18 else "boa noite"
        return "Olá, {}! Seja bem-vindo à pizzaria. {}".format(periodo, FRASE_PEDE_CPF)

    def _inicio(self, texto):
        # tem gente q ja chega falando o cpf, ai nem precisa pedir
        if len(extrair_cpf(texto)) >= 11:
            return self._receber_cpf(texto)
        return self.saudacao()

    def _receber_cpf(self, texto):
        self.etapa = "aguardando_cpf"
        if RECUSA_DE_CPF.search(_normalizar(texto)):
            return self._seguir_sem_conta("Tudo bem, sem problemas.")

        digitos = self._cpf_parcial + extrair_cpf(texto)
        # responder "oi" a saudacao nao eh errar o cpf
        if not digitos and CUMPRIMENTO.match(_normalizar(texto)):
            return FRASE_PEDE_CPF
        # a fala eh cortada depois de 1,2 s de silencio, entao quem dita com pausa chega em pedacos
        if 3 <= len(digitos) < 11:
            self._cpf_parcial = digitos
            return "Entendi {} números. Pode falar o restante?".format(len(digitos))
        self._cpf_parcial = ""
        if len(digitos) != 11:
            if self._pergunta_sobre_dados(texto):
                return "Para isso, preciso do seu CPF primeiro. Pode falar os onze números, por favor?"
            return self._cpf_nao_entendido("Não consegui entender o CPF. Pode falar os onze números, por favor?")

        db = self._sessao()
        try:
            cliente = repositorio.buscar_cliente_por_cpf(db, digitos)
        except ValueError:
            # digito verificador nao bate: quase sempre eh o whisper q ouviu um numero errado
            return self._cpf_nao_entendido("Esse CPF parece inválido. Pode repetir devagar, por favor?")
        except Exception:
            logger.warning("chamada=%s etapa=buscar_cliente categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        if cliente:
            self._identificar(cliente.id, cliente.nome, cliente.endereco, cliente.telefone)
            return "Achei seu cadastro, {}! O que vai querer hoje?".format(self._primeiro_nome())

        self.cadastro = {"cpf": digitos}
        self.etapa = "oferecendo_cadastro"
        return "Não encontrei nenhuma conta com esse CPF. Deseja criar uma conta agora?"

    def _cpf_nao_entendido(self, frase):
        self._erros_de_cpf += 1
        if self._erros_de_cpf >= TENTATIVAS_DE_CPF:
            return self._seguir_sem_conta("Não consegui confirmar o seu CPF.")
        return frase

    def _seguir_sem_conta(self, inicio):
        # sem saida aqui, quem nao quer ou nao consegue falar o cpf ficaria preso na mesma pergunta
        self.cadastro = {}
        self._cpf_parcial = ""
        self._erros_de_cpf = 0
        self.etapa = "sem_cadastro"
        return inicio + " Posso tirar dúvidas sobre o cardápio. Para fazer um pedido, diga que quer informar o CPF."

    def _desfazer_identificacao(self):
        # cpf de outra pessoa: nada do que foi carregado pode seguir nesta chamada
        self.cliente_id = None
        self.nome = None
        self.telefone = None
        self.endereco_do_cadastro = None
        self.historico = []
        self._limpar_pedido()
        self._comanda_desatualizada = True
        self.etapa = "aguardando_cpf"
        return "Desculpe pelo engano. Pode falar o seu CPF novamente?"

    def _desistiu_do_cadastro(self, texto):
        return bool(DESISTIU_DO_CADASTRO.search(_normalizar(texto)))

    def _receber_aceite(self, texto):
        # percebeu o erro depois do "nao encontrei": sem isso, o cpf novo era tratado como sim ou nao
        if len(extrair_cpf(texto)) == 11:
            self.cadastro = {}
            return self._receber_cpf(texto)
        if CPF_ERRADO.search(_normalizar(texto)):
            self.cadastro = {}
            self.etapa = "aguardando_cpf"
            return "Sem problemas. Pode falar o CPF novamente?"
        resposta = sim_ou_nao(texto)
        if resposta is None:
            return "Desculpe, não entendi. Quer criar uma conta? Responda sim ou não."
        if resposta:
            self.etapa = "aguardando_nome"
            return "Ótimo! Qual é o seu nome completo?"
        self.cadastro = {}
        self.etapa = "sem_cadastro"
        return ("Tudo bem! Sem conta eu não consigo registrar pedidos, "
                "mas posso tirar suas dúvidas sobre o cardápio.")

    def _pergunta_sobre_dados(self, texto):
        normalizado = _normalizar(texto)
        return bool(CONSULTA_HISTORICO.search(normalizado) or CONSULTA_RECOMENDACAO.search(normalizado))

    def _receber_nome(self, texto):
        if self._desistiu_do_cadastro(texto):
            return self._seguir_sem_conta("Tudo bem, cancelei o cadastro.")
        # sem isso, "o que voce recomenda" entrava no banco como nome do cliente
        if self._pergunta_sobre_dados(texto):
            return "Posso ajudar com isso logo depois do cadastro. Qual é o seu nome completo?"
        nome = extrair_nome(texto)
        if not nome or (sim_ou_nao(texto) is not None and len(nome.split()) <= 2):
            return "Não entendi o seu nome. Pode repetir, por favor?"
        self.cadastro["nome"] = nome
        self.etapa = "aguardando_telefone"
        return "Prazer, {}! Qual é o seu telefone com DDD?".format(nome.split()[0])

    def _receber_telefone(self, texto):
        if self._desistiu_do_cadastro(texto):
            return self._seguir_sem_conta("Tudo bem, cancelei o cadastro.")
        digitos = extrair_digitos(texto)
        if not digitos and sim_ou_nao(texto) is False:
            # "nao tenho", "prefiro nao falar": telefone eh opcional no banco
            self.cadastro["telefone"] = None
        elif len(digitos) in (10, 11):
            self.cadastro["telefone"] = digitos
        else:
            return "Não consegui entender o telefone. Pode falar o DDD e o número, por favor?"
        self.etapa = "aguardando_endereco"
        return "E qual é o endereço para entrega?"

    def _receber_endereco(self, texto):
        if self._desistiu_do_cadastro(texto):
            return self._seguir_sem_conta("Tudo bem, cancelei o cadastro.")
        if self._pergunta_sobre_dados(texto):
            return "Posso ajudar com isso logo depois do cadastro. Qual é o endereço para entrega?"
        endereco = extrair_endereco(texto)
        if not endereco:
            return "Não entendi o endereço. Pode falar a rua, o número e o bairro?"
        self.cadastro["endereco"] = endereco
        self.etapa = "confirmando_cadastro"

        partes = ["nome {}".format(self.cadastro["nome"])]
        if self.cadastro.get("telefone"):
            partes.append("telefone {}".format(formatar_telefone(self.cadastro["telefone"])))
        partes.append("endereço {}".format(endereco))
        return "Vou confirmar: {}. Está tudo certo?".format(", ".join(partes))

    def _receber_confirmacao(self, texto):
        if self._desistiu_do_cadastro(texto):
            return self._seguir_sem_conta("Tudo bem, cancelei o cadastro.")
        resposta = sim_ou_nao(texto)
        if resposta is None:
            return "Os dados estão certos? Responda sim ou não."
        if resposta is False:
            # o cpf ja foi conferido, entao refaz so o resto
            self.cadastro = {"cpf": self.cadastro["cpf"]}
            self.etapa = "aguardando_nome"
            return "Sem problemas, vamos de novo. Qual é o seu nome completo?"

        db = self._sessao()
        try:
            cliente = repositorio.criar_cliente(
                db,
                self.cadastro["nome"],
                self.cadastro["cpf"],
                telefone=self.cadastro.get("telefone"),
                endereco=self.cadastro.get("endereco"),
            )
            cliente_id, nome, endereco = cliente.id, cliente.nome, cliente.endereco
            telefone = cliente.telefone
        except ValueError:
            # cpf q alguem cadastrou no meio tempo, nome grande demais...
            logger.warning("chamada=%s etapa=cadastrar_cliente categoria=validacao", self.id_chamada)
            self.cadastro = {}
            self.etapa = "aguardando_cpf"
            return "Não consegui criar a conta com esses dados. " + FRASE_PEDE_CPF
        except Exception:
            logger.warning("chamada=%s etapa=cadastrar_cliente categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        self.cadastro = {}
        self._identificar(cliente_id, nome, endereco, telefone)
        return "Pronto, {}, sua conta foi criada! O que vai querer hoje?".format(
            self._primeiro_nome())

    def _identificar(self, cliente_id, nome, endereco, telefone=None):
        self.cliente_id = cliente_id
        self.nome = nome
        self.telefone = telefone
        self.endereco_do_cadastro = endereco
        self._erros_de_cpf = 0
        self.etapa = "identificado"

    def _primeiro_nome(self):
        return self.nome.split()[0]

    def _carregar_llama(self):
        if self._conversar is None:
            from agente.services.llm_service import conversar
            self._conversar = conversar
        return self._conversar

    # --- pedido: o llama entende, o python confere, o cliente confirma e o python grava ---

    def _montar_pedido(self, texto):
        db = self._sessao()
        try:
            if eh_consulta(texto) and PERGUNTA_DE_TAMANHO.search(_normalizar(texto)):
                return FRASE_TAMANHO_UNICO
            sem_tamanho, citou_tamanho = remover_tamanho(texto)
            if not citou_tamanho:
                return self._montar_pedido_com(db, texto)
            if not _normalizar(sem_tamanho):
                return FRASE_TAMANHO_UNICO + " Pode falar o produto e a quantidade?"
            return FRASE_TAMANHO_UNICO + " " + self._montar_pedido_com(db, sem_tamanho)
        except SQLAlchemyError:
            # erro do llama (ollama fechado) sobe de proposito: o turno_de_voz avisa na tela
            logger.warning("chamada=%s etapa=montar_pedido categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

    def _montar_pedido_com(self, db, texto):
        normalizado = _normalizar(texto).strip()
        if NAO_SOU_EU.search(normalizado):
            return self._desfazer_identificacao()
        sugestoes, self._sugestoes = self._sugestoes, []
        if sugestoes and normalizado in ACEITES_DA_SUGESTAO:
            if len(sugestoes) > 1:
                self._sugestoes = sugestoes
                return "Qual você quer: {}?".format(_juntar(sugestoes, "ou"))
            texto = "uma " + sugestoes[0]
            normalizado = _normalizar(texto)
        elif sugestoes and normalizado in RESPOSTAS_VAGAS_A_SUGESTAO:
            self._sugestoes = sugestoes
            return "Para anotar, me diga o produto e a quantidade. Por exemplo: uma {}.".format(sugestoes[0])
        if comando_negado(texto):
            self._fechamento_solicitado = False
            self._token_resumo = None
            return "Tudo bem, mantive seu pedido como estava. Pode continuar escolhendo."
        if set(normalizado.split()) & {"taxa", "frete", "gratis", "gratuita", "gratuito",
                                       "prazo", "desconto", "demora"}:
            fala = "A pizzaria precisa confirmar a taxa, o prazo de entrega e se há desconto."
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            self._token_resumo = None
            return fala
        if eh_consulta(texto):
            self._referencia = None
            self._fechamento_solicitado = False
            self._token_resumo = None
            return self._consultar(db, texto)
        if FECHAR.search(normalizado):
            self._fechamento_solicitado = "nao" not in normalizado.split()
        if self._troca_pendente:
            if normalizado in {"cancele a troca", "cancelar a troca", "desisti da troca"}:
                self._troca_pendente = False
                self._pendencia = self._pendencia_antes_da_troca
                self._pendencia_antes_da_troca = None
                if self._controle:
                    self._controle.definir_pendencia(self._pendencia)
                fala = self._continuar_pedido()
                self.historico.extend([{"role": "user", "content": texto},
                                       {"role": "assistant", "content": fala}])
                return fala
            if not PEDIDO_DE_TROCA.search(normalizado):
                return self._esclarecer(self._pendencia)
        if PEDIDO_DE_TROCA.search(normalizado):
            if not self._troca_pendente:
                self._pendencia_antes_da_troca = self._pendencia
            self._troca_pendente = True
            self._pendencia = "Pode repetir a troca, informando os produtos e as quantidades?"
            self._token_resumo = None
            if self._controle:
                self._controle.definir_pendencia(self._pendencia)
            problemas = self._trocar_itens(db, texto)
            self._troca_pendente = bool(problemas)
            if problemas:
                self._pendencia = (" ".join(problemas) +
                                   ' Repita a troca completa ou diga "cancele a troca".')
            else:
                self._pendencia = self._pendencia_antes_da_troca
                self._pendencia_antes_da_troca = None
            if self._controle:
                self._controle.definir_pendencia(self._pendencia)
            fala = self._esclarecer(self._pendencia) if self._pendencia else self._continuar_pedido()
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            return fala
        if " ".join(CORTESIA.sub("", normalizado).split()) in FALAS_DE_FECHAR:
            return self._fechar_pedido()
        if confirmacao_explicita(texto):
            if self._pendencia:
                return self._esclarecer(self._pendencia)
            return "Você pode continuar escolhendo. Quando terminar, diga que posso fechar o pedido."
        cardapio = repositorio.listar_cardapio(db)

        turno = {"role": "user", "content": texto}
        mensagens = [{"role": "system", "content": self._prompt_do_pedido(cardapio)}]
        # Uma fala ainda não interpretada impede confirmar o carrinho anterior,
        # inclusive se o Ollama falhar ou devolver uma resposta inválida.
        proposto, duvida, evidencias = interpretar(
            texto, cardapio, self.carrinho, self._duvida_item, self._referencia)
        self._pendencia = self._pergunta_do_campo(duvida)
        self._token_resumo = None
        if self._controle:
            self._controle.definir_pendencia(self._pendencia)
        mensagens += self.historico + [turno]
        palavras = set(normalizado.split())
        fala_de_pagamento = bool(palavras & (set(repositorio.SINAIS_DE_PAGAMENTO) | {"cartao", "maquininha"}))
        # o endereco vem da propria fala: testando, o modelo demorava e ainda inventava itens no json
        endereco_na_fala = ENDERECO_NA_FALA.search(texto)
        endereco_falado = None
        if endereco_na_fala:
            endereco_falado = extrair_endereco(FIM_DO_ENDERECO.sub("", endereco_na_fala.group()))
        fala_de_endereco = bool(palavras & {"endereco", "entrega"}) and not endereco_falado
        so_adicoes = bool(evidencias) and all(e["acao"] == "adicionar" for e in evidencias)
        # item novo, pagamento e pergunta de esclarecimento ja saem do codigo, e esperar o modelo aqui
        # custava ate 1 minuto por fala no notebook sem gpu. correcao e remocao continuam passando por
        # ele: se o modelo falhar, o pedido fica como estava
        resolvida = so_adicoes or (not evidencias and (duvida or fala_de_pagamento or endereco_falado))
        if resolvida and not fala_de_endereco:
            dados = {"itens": [], "endereco": None}
        else:
            if self.ultimo_rastro is not None:
                self.ultimo_rastro["mensagens_modelo"] = deepcopy(mensagens)
            bruto = self._carregar_llama()(mensagens, formato=ESQUEMA_DO_PEDIDO)
            if self.ultimo_rastro is not None:
                self.ultimo_rastro["resposta_modelo"] = bruto

            try:
                dados = interpretar_resposta(bruto)
            except ValueError:
                logger.warning("chamada=%s etapa=interpretar_pedido categoria=modelo_invalido", self.id_chamada)
                return self._esclarecer(self._pendencia)

        self.historico.append(turno)
        # O retrato COMPLETO do modelo é apenas uma proposta auditável. Somente a
        # transcrição e os campos pendentes da sessão autorizam editar o rascunho.
        problemas = self._atualizar_carrinho(db, proposto) if evidencias else []
        self._duvida_item = duvida
        if self.ultimo_rastro is not None:
            self.ultimo_rastro["alteracoes_autorizadas"] = evidencias
            self.ultimo_rastro["proposta_modelo"] = dados["itens"]
        self._referencia = evidencias[0]["produto"] if len(evidencias) == 1 else None
        # o pagamento sai da fala do cliente, nao do llama: testando, o modelo transformava
        # "no cartao" em "credito" sozinho, e cobrar na modalidade errada eh pior q perguntar
        problemas += self._atualizar_pagamento(texto)
        self._pendencia = (self._pergunta_do_campo(duvida) if duvida else
                           (problemas[0] if problemas else None))
        if self._controle:
            self._controle.definir_pendencia(self._pendencia)

        endereco = str(dados.get("endereco") or "").strip()
        if (len(endereco) >= 5 and _normalizar(endereco) in normalizado
                and re.search(r"\b(?:endereco|entrega|rua|avenida)\b", normalizado)):
            self.endereco_entrega = endereco
        if endereco_falado:
            self.endereco_entrega = endereco_falado

        if self._pendencia:
            fala = self._esclarecer(self._pendencia)
            if evidencias:
                fala = self._reconhecer_alteracoes(evidencias) + " " + fala
        elif self._fechamento_solicitado:
            fala = self._fechar_pedido()
        else:
            self._tentativas = 0
            self._ultima_pergunta = None
            if evidencias:
                fala = self._reconhecer_alteracoes(evidencias) + " Pode continuar escolhendo."
            elif endereco_falado:
                fala = "Certo, a entrega será em {}. Pode continuar escolhendo.".format(endereco_falado)
            else:
                fala = "Entendido. Você pode continuar escolhendo ou pedir para fechar."

        self.historico.append({"role": "assistant", "content": fala})
        return fala

    def _reconhecer_alteracoes(self, evidencias):
        verbos = {"adicionar": "Anotei", "remover": "Retirei", "corrigir": "Ajustei para"}
        return " ".join("{} {} {}{}.".format(verbos[e["acao"]], e["quantidade"], e["produto"],
                        " ({})".format(e["observacao"]) if e.get("observacao") else "") for e in evidencias)

    def _pergunta_do_campo(self, duvida):
        if not duvida:
            return "Não consegui interpretar essa alteração. Pode repetir o produto e a quantidade?"
        campo = duvida["campo"]
        if campo == "quantidade":
            return "Quantas unidades inteiras{} você deseja?".format(
                " de " + duvida["produto"] if duvida.get("produto") else "")
        if campo == "observacao":
            return "Qual é a observação para {}?".format(duvida["produto"])
        if campo == "intencao":
            return "Você deseja alterar o pedido agora? Diga o produto e a quantidade."
        candidatos = duvida.get("candidatos", [])
        if duvida.get("nao_encontrado"):
            return "Não encontrei {} no cardápio. Pode repetir o nome do produto?".format(duvida["nao_encontrado"])
        if candidatos:
            if len(candidatos) <= 4:
                return "Qual produto você quer: {}?".format(_juntar(candidatos, "ou"))
            return "Temos {} opções de {}. Qual é o sabor que você quer?".format(
                len(candidatos), duvida.get("trecho", "produto"))
        qtd = duvida.get("quantidade")
        if qtd:
            if qtd == 1:
                return "Não entendi um dos produtos. Pode repetir o nome dele?"
            return "Entendi {} unidades, mas faltou o nome. Qual é o produto dessas {} unidades?".format(qtd, qtd)
        return "Não identifiquei o produto no cardápio. Pode repetir só o nome do produto?"

    def _esclarecer(self, pergunta):
        if self._ultima_pergunta == pergunta:
            self._tentativas += 1
        else:
            self._ultima_pergunta, self._tentativas = pergunta, 1
        if self._tentativas == 1:
            return pergunta
        if self._tentativas == 2:
            return "Vamos por partes, uma coisa por vez. " + pergunta
        return "Ainda não ficou claro. Tente reformular com outras palavras. " + pergunta

    def _continuar_pedido(self):
        if self._pendencia:
            return self._esclarecer(self._pendencia)
        return self._fechar_pedido() if self._fechamento_solicitado else "Alteração anotada. Pode continuar escolhendo."

    def _consultar(self, db, texto):
        produtos = repositorio.listar_cardapio(db)
        normalizado = _normalizar(texto)
        _, citados = mencoes(texto, produtos)
        if RECLAMA_DO_PEDIDO.search(normalizado):
            fala = self._falar_pedido_atual(" O que você quer mudar?")
        elif CONSULTA_PEDIDO_ATUAL.search(normalizado):
            fala = self._falar_pedido_atual(" Pode continuar escolhendo.")
        elif CONSULTA_HISTORICO.search(normalizado):
            fala = self._falar_historico(db, normalizado)
        elif CONSULTA_RECOMENDACAO.search(normalizado):
            fala = self._recomendar(db, normalizado, produtos)
        elif cardapio_completo(texto):
            fala = "Cardápio completo. " + " ".join(
                "{}: {}.".format(p.nome, preco_falado(p.preco)) for p in produtos)
            if not produtos:
                fala = "Não há produtos disponíveis no cardápio neste momento."
        elif re.search(r"\b(?:preco|precos|custa|custam|quanto)\b", normalizado) and citados:
            unicos = {p.id: p for _, _, candidatos in citados for p in candidatos}
            fala = " ".join("{} custa {}.".format(p.nome, preco_falado(p.preco)) for p in unicos.values())
        elif re.search(r"\b(?:ingredientes|contem|leva|tem cebola)\b", normalizado) and citados:
            unicos = {p.id: p for _, _, candidatos in citados for p in candidatos}
            fala = " ".join("{}: {}.".format(p.nome, p.descricao or "ingredientes não informados")
                            for p in unicos.values())
        else:
            mensagens = [{"role": "system", "content": self._prompt_do_pedido(produtos)}] + self.historico + [
                {"role": "user", "content": texto}]
            if self.ultimo_rastro is not None:
                self.ultimo_rastro["mensagens_modelo"] = deepcopy(mensagens)
            bruto = self._carregar_llama()(mensagens, formato=ESQUEMA_DO_PEDIDO)
            if self.ultimo_rastro is not None:
                self.ultimo_rastro["resposta_modelo"] = bruto
            try:
                fala = interpretar_resposta(bruto)["resposta"].strip()
                if not fala or re.search(r"\b(?:anotei|adicionei|confirmado|registrado|pagar|confirmar)\b", _normalizar(fala)):
                    raise ValueError("consulta não altera pedido")
            except (ValueError, TypeError, KeyError, AttributeError):
                fala = "Qual informação do cardápio você gostaria de consultar?"
        self.historico.extend([{"role": "user", "content": texto}, {"role": "assistant", "content": fala}])
        return fala

    def _falar_pedido_atual(self, complemento):
        if not self.carrinho:
            return "Ainda não anotei nada neste pedido. O que vai querer?"
        itens = ["{} {}".format(i["quantidade"], i["produto"]) for i in self.carrinho]
        total = sum((i["preco"] * i["quantidade"] for i in self.carrinho), Decimal("0.00"))
        return "Até agora anotei {}, subtotal de {}.".format(_juntar(itens), preco_falado(total)) + complemento

    def _falar_historico(self, db, normalizado):
        # com pedido em andamento, "o que eu pedi" sem falar do passado eh sobre o pedido de agora
        fala_do_passado = re.search(r"\b(?:ultim\w+|anterior\w*|passad\w+|historico|meus pedidos|ja pedi)\b",
                                    normalizado)
        if self.carrinho and not fala_do_passado:
            return self._falar_pedido_atual(" Pode continuar escolhendo.")

        # so le pelo cliente_id desta chamada: o historico de outra pessoa nunca entra aqui
        if not self.cliente_id:
            return "Sem uma conta, eu não tenho histórico de pedidos para consultar."

        varios = re.search(r"\b(?:pedidos|compras|historico)\b", normalizado)
        pedidos = repositorio.historico_cliente(db, self.cliente_id, limite=3 if varios else 1)
        if not pedidos:
            return "Você ainda não tem pedidos anteriores."

        def descrever(pedido):
            itens = ["{} {}".format(i.quantidade, i.produto.nome) for i in pedido.itens]
            return "em {}: {}, total de {}.".format(
                pedido.criado_em.astimezone().strftime("%d/%m"), _juntar(itens) or "sem itens registrados",
                preco_falado(pedido.total))

        if len(pedidos) == 1:
            fala = "Seu último pedido foi " + descrever(pedidos[0])
        else:
            fala = "Seus últimos {} pedidos foram: {}".format(
                len(pedidos), " ".join(descrever(p) for p in pedidos))
        return fala + " Se quiser repetir, diga os produtos e as quantidades."

    def _recomendar(self, db, normalizado, produtos):
        # "quais bebidas voce indica" vira "bebida", igual a busca por categoria do cardapio
        singular = " ".join(p.rstrip("s") for p in normalizado.split())
        categoria = next((c for c in ("pizza doce", "pizza salgada", "pizza", "bebida", "sobremesa", "borda")
                          if re.search(r"\b" + c + r"\b", singular)), None)
        if not categoria:
            categoria = next((SINONIMOS_DE_CATEGORIA[p] for p in singular.split()
                              if p in SINONIMOS_DE_CATEGORIA), None)
        convite = " Se quiser pedir, diga o produto e a quantidade."

        favoritos = []
        # "o que mais sai da casa" pergunta da pizzaria, nao do cliente
        if self.cliente_id and "casa" not in normalizado.split():
            favoritos = repositorio.itens_mais_pedidos_do_cliente(db, self.cliente_id, 1, categoria)
        if favoritos:
            produto, quantidade = favoritos[0]
            self._sugestoes = [produto.nome]
            return "Pelo seu histórico, você mais pede {}, com {} {} até agora. Hoje custa {}.".format(
                produto.nome, quantidade, "unidade" if quantidade == 1 else "unidades",
                preco_falado(produto.preco)) + convite

        # cliente novo, sem conta ou sem nada daquela categoria: vale o que a casa mais vende
        campeoes = repositorio.itens_mais_pedidos_da_casa(db, 2, categoria)
        if campeoes:
            nomes = [produto.nome for produto, _ in campeoes]
            self._sugestoes = nomes
            inicio = "Os mais pedidos da casa são {}." if len(nomes) > 1 else "O mais pedido da casa é {}."
            return inicio.format(_juntar(nomes)) + convite

        # ninguem pediu nada ainda: sugere do cardapio, sem oferecer agua pra quem pediu sobremesa
        if categoria:
            opcoes = [p for p in produtos if categoria in _normalizar(p.categoria)]
        else:
            opcoes = [p for p in produtos if "salgada" in _normalizar(p.categoria)] or produtos
        if opcoes:
            self._sugestoes = [opcoes[0].nome]
            return "Uma opção do cardápio é {}.".format(opcoes[0].nome) + convite
        if categoria:
            return "Não temos opções de {} disponíveis agora.".format(categoria)
        return "Não há produtos disponíveis no cardápio neste momento."

    def _trocar_itens(self, db, texto):
        # shortcut: uma troca explícita por fala, sem novas observações ou outras
        # alterações. Fora desse formato, esclareça antes de ampliar a gramática.
        if re.search(r"[-+−]\s*\d", texto):
            return ["Informe quantidades inteiras positivas, sem sinais."]
        texto = re.sub(r"\s+por favor$", "", _normalizar(texto))
        partes = re.fullmatch(
            r"(?:(?:sim|nao)\s+mas\s+|sim\s+)?"
            r"(?:(?:pode|quero|gostaria de)\s+)?"
            r"(?:troque|trocar|troca|substitua|substituir)\s+(.+?)\s+por\s+(.+)", texto,
        )
        if not partes or not self._controle or not self._controle.itens:
            return ["Pode dizer qual produto deseja trocar e por qual produto, com as quantidades?"]
        retirar, origem = _item_da_troca(partes[1])
        acrescentar, destino = _item_da_troca(partes[2])
        origem, destino = _nome_na_troca(origem), _nome_na_troca(destino)
        itens = [i for i in self._controle.itens
                 if origem and f" {origem} " in f" {_nome_na_troca(i.nome)} "]
        if len(itens) != 1:
            return ["Qual item do pedido você deseja trocar? Informe também a quantidade."]
        item = itens[0]
        if retirar is None:
            if item.quantidade != 1:
                return ["Quantas unidades de {} deseja trocar?".format(item.nome)]
            retirar = 1
        produtos = [p for p in repositorio.listar_cardapio(db)
                    if destino and f" {destino} " in f" {_nome_na_troca(p.nome)} "]
        if not produtos:
            return ["Não temos esse produto no cardápio ou a troca contém mais de uma alteração. "
                    "Pode repetir uma troca por vez, com os nomes e as quantidades?"]
        if len(produtos) > 1:
            return [self._pergunta_de_ambiguidade(destino, produtos)]
        if acrescentar is None:
            return ["Quantas unidades de {} deseja acrescentar na troca?".format(produtos[0].nome)]
        controle = deepcopy(self._controle)
        try:
            controle.substituir(item.id, retirar, produtos[0].id, acrescentar)
        except ErroPedido as erro:
            return [str(erro)]
        return self._atualizar_carrinho(db, [
            {"produto": i.nome, "quantidade": i.quantidade, "observacao": i.observacao}
            for i in controle.itens
        ])

    def _atualizar_carrinho(self, db, itens):
        """
        Valida o retrato completo antes de substituir o carrinho.
        Uma falha preserva os itens anteriores e exige esclarecimento.
        """
        novo = []
        problemas = []

        for item in itens:
            if not isinstance(item, dict):
                problemas.append("Pode repetir o produto e a quantidade?")
                continue
            falado = str(item.get("produto") or "").strip()
            if not falado:
                problemas.append("Pode repetir o nome do produto?")
                continue

            candidatos = repositorio.buscar_produtos(db, falado)
            if not candidatos:
                problemas.append("Não temos {} no cardápio.".format(falado))
                continue
            if len(candidatos) > 1:
                problemas.append(self._pergunta_de_ambiguidade(falado, candidatos))
                continue
            produto = candidatos[0]

            quantidade = item.get("quantidade")
            if isinstance(quantidade, bool) or not isinstance(quantidade, int) or quantidade <= 0:
                problemas.append("Quantas unidades de {} você quer?".format(produto.nome))
                continue

            if item.get("observacao") is not None and not isinstance(item["observacao"], str):
                problemas.append("Pode repetir a observação do produto?")
                continue
            observacao = (item.get("observacao") or "").strip() or None

            repetido = next((i for i in novo if i["produto"] == produto.nome
                             and i["observacao"] == observacao), None)
            if repetido:
                repetido["quantidade"] += quantidade
            else:
                novo.append({
                    "produto": produto.nome,
                    "quantidade": quantidade,
                    "preco": Decimal(str(produto.preco)),
                    "observacao": observacao,
                })

        # Uma extração incompleta nunca substitui parte do pedido anterior.
        if not problemas:
            controle = ControlePedido([
                ProdutoCardapio(p.id, p.nome, Decimal(str(p.preco)))
                for p in repositorio.listar_cardapio(db)
            ])
            for item in novo:
                produto = repositorio.buscar_produtos(db, item["produto"])[0]
                controle.adicionar(produto.id, item["quantidade"], item["observacao"] or "")
            self.carrinho = novo
            self._controle = controle
            # Agradecimentos sem itens não apagam a última venda da comanda.
            if novo:
                self._pedido_salvo = None
        self._token_resumo = None
        return problemas

    def _pergunta_de_ambiguidade(self, falado, candidatos):
        nomes = [p.nome for p in candidatos]
        if len(nomes) <= 4:
            return "Qual {} você quer: {}?".format(falado, _juntar(nomes, "ou"))
        return "Temos {} opções de {}, como {}. Qual você quer?".format(
            len(nomes), falado, _juntar(nomes[:3]))

    def _atualizar_pagamento(self, falado):
        texto = _normalizar(falado)
        palavras = set(texto.split())
        sinais = set(repositorio.SINAIS_DE_PAGAMENTO) | {"cartao", "maquininha"}
        if not palavras & sinais:
            # o cliente nao falou de pagamento nessa fala: mantem o q ja tinha
            return []
        try:
            self.pagamento = repositorio.interpretar_pagamento(falado)
            return []
        except ValueError:
            self.pagamento = None
            if "cartao" in texto or "maquininha" in texto:
                return ["No cartão de crédito ou de débito?"]
            return [FRASE_PEDE_PAGAMENTO]

    def _fechar_pedido(self):
        # so le o resumo quando nao falta nada: o cliente confirma o pedido inteiro de uma vez
        if self._pendencia:
            return self._esclarecer(self._pendencia)
        if not self.carrinho:
            return "Você ainda não pediu nada. O que vai querer?"
        if not self.pagamento:
            return FRASE_PEDE_PAGAMENTO
        if not (self.endereco_entrega or self.endereco_do_cadastro):
            return "Qual é o endereço para entrega?"
        self.etapa = "confirmando_pedido"
        return self._resumo_do_pedido()

    def _resumo_do_pedido(self):
        resumo = self._controle.resumir()
        self._token_resumo = resumo.token
        itens = ["{} {}{}".format(i.quantidade, i.nome,
                 " (solicitação: {})".format(i.observacao) if i.observacao else "")
                 for i in resumo.itens]
        return ("Vou confirmar seu pedido: {}. Subtotal dos produtos de {}. Entrega no endereço {}, "
                "pagamento {}. Posso confirmar?").format(
            _juntar(itens),
            preco_falado(resumo.subtotal),
            self.endereco_entrega or self.endereco_do_cadastro,
            PAGAMENTO_FALADO[self.pagamento],
        )

    def _receber_confirmacao_do_pedido(self, texto):
        if not confirmacao_explicita(texto):
            if _normalizar(texto).strip() in {"hmm", "talvez", ""}:
                return self._esclarecer("Posso confirmar o pedido? Responda sim ou não.")
            self.etapa = "identificado"
            self._token_resumo = None
            # "nao, tira a coca": a mesma fala ja serve pra corrigir o pedido
            if _normalizar(texto).strip() not in {"nao", "nao quero"}:
                return self._montar_pedido(texto)
            return "Tudo bem. O que você quer mudar?"

        db = self._sessao()
        try:
            self._controle.confirmar(self._token_resumo)
            pedido = repositorio.salvar_pedido(
                db,
                self.cliente_id,
                [{"produto": i["produto"], "quantidade": i["quantidade"],
                  "observacao": i["observacao"], "preco_confirmado": i["preco"]}
                 for i in self.carrinho],
                endereco_entrega=self.endereco_entrega,
                forma_pagamento=self.pagamento,
            )
            numero = pedido.id
            # Preserve a comanda antes de limpar o carrinho para o próximo pedido.
            self._pedido_salvo = {
                **self._dados_do_pedido(), "pedido_id": numero,
                "total": format(pedido.total, ".2f"),
                "endereco_entrega": pedido.endereco_entrega,
            }
        except ValueError:
            # o cardapio mudou entre o resumo e o sim (produto desativado, por exemplo)
            logger.warning("chamada=%s etapa=salvar_pedido categoria=validacao", self.id_chamada)
            self.etapa = "identificado"
            problemas = self._atualizar_carrinho(db, self.carrinho)
            self._pendencia = " ".join(problemas) or None
            if problemas:
                return self._pendencia
            return "O cardápio mudou; confira os valores atualizados. " + self._fechar_pedido()
        except Exception:
            # continua confirmando: se o cliente disser sim de novo, tenta gravar de novo
            logger.warning("chamada=%s etapa=salvar_pedido categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        self._limpar_pedido()
        self.historico = []
        self.etapa = "identificado"
        return "Pedido número {} registrado! Obrigado pela preferência, {}.".format(
            numero, self._primeiro_nome())

    def _prompt_do_pedido(self, cardapio):
        if self.carrinho:
            atual = "\n".join(
                "- {} {}{}".format(
                    i["quantidade"], i["produto"],
                    " ({})".format(i["observacao"]) if i["observacao"] else "")
                for i in self.carrinho
            )
        else:
            atual = "(vazio)"

        return "\n".join([
            _prompt_base(),
            "MODO INTEGRADO: o modelo extrai dados; somente o código apresenta o resumo, "
            "pede confirmação e registra o pedido. Siga o formato JSON abaixo.",
            "Você é o atendente de telefone de uma pizzaria e está anotando um pedido.",
            "Responda sempre com um JSON com estes campos:",
            '- "resposta": responda à pergunta atual em português do Brasil. Prefira frases curtas, '
            "mas nunca omita produtos ou preços de uma listagem completa solicitada. Sem emojis ou "
            "markdown. Não pressione pelo fechamento. Nunca diga que o pedido foi registrado ou confirmado.",
            '- "itens": uma PROPOSTA do pedido completo, sujeita à validação da fala pelo código. Parta do '
            "pedido atual abaixo, acrescente, troque ou tire o que ele disse e mantenha o resto. "
            "Use o nome exato do cardápio. Se o cliente foi vago (por exemplo só \"uma pizza\"), "
            "escreva o que ele disse, sem escolher por ele. Em uma troca, retire o item "
            "substituído antes de acrescentar o novo; não acrescente produtos de exemplos.",
            '- "endereco": só se o cliente falou um endereço de entrega diferente; senão null.',
            '- "fechar": true só quando o cliente disser que terminou o pedido (por exemplo '
            '"é só isso", "pode fechar"); senão false.',
            "Use apenas os produtos e preços do cardápio. Nunca invente produto ou preço.",
            "Consultas de preços, ingredientes, cardápio ou recomendações NÃO alteram itens. "
            "Mencionar um produto não significa pedi-lo. Nunca acrescente sugestões sem aceite explícito. "
            "Uma resposta sim só responde à pergunta imediatamente anterior; não resolve produto ambíguo.",
            "Nunca arredonde quantidades fracionadas: preserve a fração para o código pedir "
            "esclarecimento. Mantenha separadas unidades com observações diferentes. "
            "Se houver dúvida pendente, peça esclarecimento; não considere um simples sim "
            "como solução. Não invente taxa, prazo ou desconto.",
            "",
            # o que nao muda fica antes: o ollama reaproveita o inicio igual do prompt entre as falas
            "Cardápio:",
            _cardapio_em_texto(cardapio),
            "",
            "Cliente: {}".format(self.nome),
            "Pedido atual:",
            atual,
            "Pendência: {}".format(self._pendencia or "nenhuma"),
            "Pagamento: {}".format(PAGAMENTO_FALADO.get(self.pagamento, "ainda não informado")),
            "Endereço de entrega: {}".format(
                self.endereco_entrega or self.endereco_do_cadastro or "ainda não informado"),
        ])

    # --- quem nao quis conta so conversa com o llama, sem pedido ---

    def _conversar_com_llm(self, texto):
        if len(extrair_cpf(texto)) == 11:
            return self._receber_cpf(texto)
        if VOLTAR_PARA_O_CPF.search(_normalizar(texto)):
            self.etapa = "aguardando_cpf"
            return "Claro. Pode falar o seu CPF, por favor?"
        db = self._sessao()
        try:
            normalizado = _normalizar(texto)
            if (cardapio_completo(texto) or CONSULTA_HISTORICO.search(normalizado) or
                    CONSULTA_RECOMENDACAO.search(normalizado) or
                    re.search(r"\b(?:preco|precos|custa|custam|quanto)\b", normalizado)):
                return self._consultar(db, texto)
            cardapio = _cardapio_em_texto(repositorio.listar_cardapio(db))
        except SQLAlchemyError:
            logger.warning("chamada=%s etapa=ler_cardapio categoria=banco", self.id_chamada)
            return "Não consegui consultar o cardápio no sistema agora. Tente novamente em instantes."
        finally:
            db.close()

        sistema = "\n".join([
            _prompt_base(),
            "Você é o atendente de telefone de uma pizzaria. Fale em português do Brasil.",
            "Sua resposta será lida em voz alta: prefira frases curtas, sem emojis e sem markdown. "
            "Se o cliente pedir uma listagem completa, informe todos os itens e preços disponíveis.",
            "O cliente preferiu não criar conta. Sem conta não dá para registrar pedidos, "
            "só tirar dúvidas sobre o cardápio.",
            "Use apenas os produtos e preços do cardápio abaixo. Nunca invente produto ou preço.",
            "",
            "Cardápio:",
            cardapio,
        ])

        turno = {"role": "user", "content": texto}
        mensagens = [{"role": "system", "content": sistema}] + self.historico + [turno]
        resposta = self._carregar_llama()(mensagens).strip()
        self.historico.append(turno)
        self.historico.append({"role": "assistant", "content": resposta})
        return resposta


def _cardapio_em_texto(produtos):
    return "\n".join(
        "- {} ({}): {}".format(p.nome, p.categoria, _formatar_preco(p.preco)) for p in produtos
    )
