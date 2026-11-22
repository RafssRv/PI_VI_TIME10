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
                                   AINDA_NAO_ACABOU, FECHAR, FIM_DO_PEDIDO, RECLAMA_DO_PEDIDO,
                                   TAMANHO_INDISPONIVEL, TAMANHOS_BASE,
                                   cardapio_completo, comando_negado, eh_consulta, interpretar, mencoes,
                                   separar_tamanhos, tamanhos_do_banco)

from sqlalchemy.exc import SQLAlchemyError

import repositorio
from interpretacao import (
    ESQUEMA_DO_PEDIDO, MUDA_PARA, PEDIDO_DE_TROCA, _item_da_troca, _nome_na_troca, _normalizar,
    confirmacao_composta, confirmacao_explicita, extrair_digitos, extrair_endereco, extrair_nome,
    interpretar_resposta, parece_confirmacao, sim_ou_nao,
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
                              "ta bom", "perfeito", "pode", "pode sim", "sim pode", "sim por favor", "ta", "ta ok"}
CUMPRIMENTO = re.compile(r"^(?:oi|ola|alo|opa|e ai|bom dia|boa tarde|boa noite|tudo bem|tudo bom)\b")
CORTESIA = re.compile(r"\b(?:obrigad[oa]|valeu|por favor|viu)\b")
# falas inteiras que nao pedem nada: sem isto viravam "Não temos oi no cardápio"
_SAUDACAO = r"(?:oi|ola|alo|opa|e ai|bom dia|boa tarde|boa noite)"
SO_CUMPRIMENTO = re.compile(r"{0}(?: {0})*(?: (?:tudo bem|tudo bom|como vai))?".format(_SAUDACAO))
SO_QUER_PEDIR = re.compile(r"(?:{} )?(?:eu )?(?:quero|queria|gostaria de|vou|posso|preciso) "
                           r"(?:fazer |realizar )?(?:um |o |meu )?(?:pedir|pedido)(?: agora| ai)?".format(_SAUDACAO))
PEDE_TEMPO = re.compile(r"(?:so )?(?:um|1) (?:momento|minuto|minutinho|segundo|instante)|espera(?: ai| um pouco)?|"
                        r"pera(?: ai)?|perai|calma(?: ai)?|deixa eu (?:ver|pensar)|vou (?:ver|pensar)|"
                        r"(?:to|estou) (?:vendo|pensando)")
# "pode repetir?", "o quê?", "não ouvi": o cliente quer ouvir de novo a última fala
PEDE_REPETIR = re.compile(
    r"(?:(?:voce |vc )?(?:pode|poderia|podia|consegue) )?(?:repetir|repete|repita|falar de novo|fala de novo|"
    r"dizer de novo|diz de novo|falar outra vez|fala outra vez)(?: (?:pra mim|de novo|novamente|o que disse|"
    r"o que voce disse))?|o que|o que voce disse|o que voce falou|como|como e|como assim|hein|"
    r"nao (?:ouvi|escutei|entendi)(?: nada| direito| o que voce disse)?|nao deu pra (?:ouvir|entender)|perdao")
# "hmm", "tá", "entendi": não pedem nada. Não confirmam o pedido: só confirmacao_explicita autoriza gravar
HESITACAO = re.compile(r"(?:h+m+|hu+m+|u+h*m+|e+h+|a+h*n+)(?: (?:h+m+|hu+m+|u+h*m+|e+h+|a+h*n+))*")
# "tem cerveja?", "vocês vendem vinho?": o que vem depois do verbo, até três palavras
TEM_FORA_DO_CARDAPIO = re.compile(r"(?:(?:voces|vcs|vc|voce|ai|e)\s+)*(?:tem|teria|vende|vendem|servem|trabalham com)\s+"
                                  r"(?:(?:a|o|um|uma|algum|alguma)\s+)?(\w+(?:\s+\w+){0,2}?)(?:\s+(?:ai|ainda|hoje|tambem))?")
# serviço e pagamento não são item do cardápio: "tem entrega?" não é "não temos entrega no cardápio"
NAO_E_ITEM = {"entrega", "delivery", "troco", "maquininha", "cartao", "pix", "promocao", "promocoes", "desconto",
              "taxa", "frete", "horario", "estacionamento", "opcao", "opcoes", "sabor", "sabores", "tamanho",
              "tamanhos", "cardapio", "menu", "como", "que", "algo", "mais", "vaga", "atendente", "alguem"}
# perguntas sobre o serviço. "posso pagar no pix" fica de fora: é o cliente escolhendo, não perguntando
PERGUNTA_DE_PAGAMENTO = re.compile(
    r"\b(?:aceita|aceitam|passa|passam|trabalha com|trabalham com)\b.*"
    r"\b(?:cartao|credito|debito|pix|dinheiro|vale|vr|va|ticket|alelo|sodexo|picpay|boleto|cheque)\b"
    r"|\btem maquininha\b")
PAGAMENTO_QUE_NAO_ACEITA = re.compile(
    r"\b(?:vale(?: refeicao| alimentacao)?|vr|va|ticket|alelo|sodexo|picpay|boleto|cheque)\b")
NOMES_DE_PAGAMENTO = {"vale refeicao": "vale-refeição", "vale alimentacao": "vale-alimentação", "vr": "VR",
                      "va": "VA", "ticket": "Ticket", "alelo": "Alelo", "sodexo": "Sodexo", "picpay": "PicPay"}
FORMAS_ACEITAS = "Pix, dinheiro, cartão de crédito ou débito"
ESCOLHE_PAGAMENTO = re.compile(r"(?:(?:eu|entao)\s+)?(?:posso|da pra|pode ser|seria)\s+(?:pagar\s+)?"
                               r"(?:(?:no|na|em|com|pelo)\s+)?(?:pix|pics|dinheiro|cartao|credito|debito|maquininha)\b")
# "entregam no centro?": a área de entrega a pizzaria confirma, não dá pra prometer
ENTREGA_EM_LUGAR = re.compile(r"\bentregam?\s+(?:no|na|em|pro|pra|ate|aqui|ai)\b")
PERGUNTA_DE_ENTREGA = re.compile(r"\b(?:tem|faz|fazem|faria) (?:entrega|delivery)\b|\bentregam\b|\bvoces entregam\b")
PERGUNTA_DE_HORARIO = re.compile(r"\bque horas\b|\bhorario\b|\b(?:abrem|fecham)\b")
# "não, quero mudar", "espera, quero alterar uma coisa": sai da confirmação sem dizer ainda o quê
QUER_MUDAR = re.compile(r"(?:nao\s+)?(?:(?:espera|pera|calma)\s+)?(?:(?:eu\s+)?(?:quero|queria|preciso|vou|vamos)\s+)?"
                        r"(?:mudar|alterar|trocar|corrigir|mexer)(?:\s+(?:uma coisa|uma coisinha|algo|o pedido|"
                        r"umas coisas|um item|uma parte))?|nao(?:\s+quero)?|nao\s+(?:espera|pera|calma)|espera|pera|"
                        r"nao\s+(?:confirma|confirme|pode confirmar|precisa confirmar|e isso|esta certo|ta certo)")
DEIXA_PRA_LA = {"esquece", "esquece isso", "esquece entao", "deixa pra la", "deixa quieto", "nao precisa",
                "nao precisa mais", "deixa"}
SO_CONCORDA = {"ta", "e", "entendi", "sei", "ah", "ah ta", "ta ok", "blz", "ta entendi", "ah entendi", "ok entendi"}
SINONIMOS_DE_CATEGORIA = {"refrigerante": "bebida", "refri": "bebida", "suco": "bebida", "agua": "bebida"}
ENDERECO_NA_FALA = re.compile(r"\b(?:rua|avenida|av|travessa|alameda|estrada|rodovia)\b.*", re.IGNORECASE)
FRASE_PEDE_TAMANHO = "pequena, média ou grande?"
# so valem ate a primeira leitura da tabela tamanho: dali em diante as opcoes sao as do banco
OPCOES_DE_TAMANHO = {"pizza": FRASE_PEDE_TAMANHO, "refrigerante": "lata, 600 ml ou 2 litros?"}
EXEMPLO_DE_TAMANHOS = {"pizza": "uma grande e uma média", "refrigerante": "uma de 2 litros e uma de 600 ml"}
QUER_MUDAR_ENDERECO = re.compile(
    r"\b(?:mudar|muda|trocar|troca|alterar|altera|corrigir|corrige|outro|novo)\b.*\bendereco\b|"
    r"\bendereco\b.*\b(?:errado|outro|novo|diferente)\b"
)
# palavras da propria pergunta, que podem vir depois do nome do produto sem fazer parte dele
PALAVRAS_DA_CONSULTA = {
    "de", "do", "da", "dos", "das", "a", "o", "as", "os", "e", "ou", "um", "uma", "cada", "que", "qual", "quais",
    "quanto", "custa", "custam", "preco", "precos", "valor", "tem", "leva", "contem", "vem", "ingredientes",
    "agora", "entao", "la", "pra", "para", "mim", "voces", "vcs", "sai", "fica", "esta", "ta", "sao", "eh",
}
# "quanto ficou?", "qual o total?": o valor sai do carrinho, o modelo nao faz conta. so vale sem produto
# na frase, pq "quanto fica a calabresa?" pergunta o preco dela
PERGUNTA_DO_TOTAL = re.compile(
    r"\bquanto (?:que )?(?:ficou|deu|saiu|vai ficar|vai dar|ta dando|esta dando)\b|"
    r"\bquanto (?:que )?(?:fica|da|e|custa|sai)(?: (?:tudo|isso|o pedido|a conta|o total|no total|ao todo))?"
    r"(?: mesmo| entao| ai)?$|"
    r"\b(?:total|valor)(?: do pedido| da conta| total)?(?: mesmo| entao| ai)?$|"
    r"\bquanto (?:eu )?(?:vou pagar|pago|devo)\b"
)
# "cancela o pedido", "tira tudo", "quero começar de novo": esvazia o rascunho, que ainda nao foi gravado
ESVAZIAR_PEDIDO = re.compile(
    r"\b(?:cancel|limp|esvazi|apag|zer|esquec)\w*\b.*\b(?:pedido|tudo|carrinho|comanda)\b|"
    r"\b(?:tir|retir|remov)\w*\s+tudo\b|\bcomecar (?:tudo )?de novo\b|\bdesisti do pedido\b"
)
# com uma troca nao entendida esperando resposta, estas falas desistem dela e o pedido fica como estava
DESISTE_DA_TROCA = {
    "cancele a troca", "cancelar a troca", "cancela a troca", "desisti da troca", "esquece a troca",
    "cancela", "cancelar", "cancele", "pode cancelar", "desisti", "esquece", "deixa", "deixa pra la",
    "deixa para la", "deixa assim", "deixa como esta", "deixa como estava", "pode deixar",
    "nao quero trocar", "nao quero mais trocar", "nao precisa", "nao precisa trocar", "nao precisa mais",
}
# sozinha, a palavra so cancela o pedido quando nao ha uma troca esperando resposta
SO_CANCELAR = {"cancela", "cancelar", "cancele", "pode cancelar", "quero cancelar"}
NAO_ESVAZIAR = re.compile(r"\bnao (?:(?:quero|precisa|vou|pode|e para|e pra) )?"
                          r"(?:cancel|limp|esvazi|apag|zer|esquec|tir|retir|remov)")
CPF_ESCRITO = re.compile(r"\b\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[.\s-]?\d{2}\b")
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

def _com_artigo(nome):
    # o cardapio nao guarda genero: esses comecos sao femininos, o resto (guarana, pudim, suco) masculino
    return ("A " if _feminino(nome) else "O ") + nome


def _feminino(nome):
    return _normalizar(nome).split()[0] in {"pizza", "borda", "coca", "agua", "fanta"}


def _da(nome):
    # "qual o tamanho da Coca-Cola" / "do Guaraná"
    return ("da " if _feminino(nome) else "do ") + nome


def _uma(tamanho):
    # "uma grande", mas "uma de 2 litros"
    return ("uma de " if tamanho[:1].isdigit() else "uma ") + tamanho


def _categorias_faladas(produtos):
    """"pizzas salgadas, pizzas doces, bebidas...": as categorias do cardápio, pizza primeiro."""
    categorias = sorted({p.categoria for p in produtos}, key=lambda c: (not c.startswith("pizza"), c))
    return [" ".join(palavra + "s" for palavra in c.split()) for c in categorias]


def _com_tamanho(nome, tamanho):
    # "Pizza de Calabresa grande": o tamanho vai depois do nome, como o cliente fala
    return "{} {}".format(nome, tamanho) if tamanho else nome


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
        # o monitor mostra o pedido da chamada mesmo se o cliente comecar outro depois
        self.ultimo_pedido_id = None
        # produto do cardapio -> grupo de tamanhos ("pizza", "refrigerante"), pra saber quem precisa de
        # tamanho, e as opcoes faladas de cada grupo ("lata, 600 ml ou 2 litros?")
        self._grupos = {}
        self._opcoes_tamanho = dict(OPCOES_DE_TAMANHO)
        self._exemplos_tamanho = dict(EXEMPLO_DE_TAMANHOS)
        self._vocabulario = TAMANHOS_BASE
        # "pode repetir?" devolve isto sem mexer no pedido
        self._ultima_resposta = None
        self._fala_da_troca = None
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
        self._repetir = None
        self._pedindo_endereco = False
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
        pedido = " ".join(CORTESIA.sub("", _normalizar(texto or "")).split())
        if self._ultima_resposta and PEDE_REPETIR.fullmatch(pedido):
            # não ouviu: repetir não pode mudar o pedido nem tirar a chamada da etapa em que está
            return self._ultima_resposta
        rastrear =self.etapa in {"identificado", "confirmando_pedido", "sem_cadastro"}
        if rastrear:
            # Só o último turno fica em memória. O validador pode salvá-lo com dados fictícios.
            self.ultimo_rastro = {"sessao": self.sessao_id, "turno": self.turno_id,
                                  "turno_voz": getattr(self, "turno_voz", None),
                                  "transcricao": texto, "antes": deepcopy(self.carrinho)}
        try:
            resposta = etapas[self.etapa](texto)
            self._ultima_resposta = resposta
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
                       "observacao": i["observacao"], "tamanho": i.get("tamanho")} for i in self.carrinho],
            "total": format(sum((i["preco"] * i["quantidade"] for i in self.carrinho),
                                Decimal("0.00")), ".2f"),
            "forma_pagamento": self.pagamento,
            "endereco_entrega": self.endereco_entrega or self.endereco_do_cadastro,
        }

    def texto_para_tela(self, texto):
        """a legenda pode estar projetada: o cpf nao aparece, mesmo ditado por extenso."""
        if self.etapa in {"inicio", "aguardando_cpf", "oferecendo_cadastro"} and len(extrair_digitos(texto)) >= 3:
            return "CPF informado"
        return CPF_ESCRITO.sub("CPF informado", texto)

    def dica_de_transcricao(self):
        """
        o que o whisper deve esperar ouvir. so vale quando a fala eh sobre o cardapio: no cpf nao ajuda
        e em nome e endereco atrapalharia. nao colocar comandos aqui: testando, o modelo repetia o fim
        da dica quando so ouvia ruido, e "e so isso" fecharia o pedido sozinho.
        """
        if self.etapa not in {"identificado", "confirmando_pedido", "sem_cadastro"} or self._pedindo_endereco:
            return None
        if self._dica is None:
            db = self._sessao()
            try:
                produtos = repositorio.listar_cardapio(db)
                tamanhos = repositorio.listar_tamanhos(db)
            except Exception:
                logger.warning("chamada=%s etapa=dica_transcricao categoria=banco", self.id_chamada)
                return None
            finally:
                db.close()
            # o whisper so le uns 220 tokens de dica: "Pizza de" em todo sabor gastava metade disso
            sabores = [re.sub(r"^Pizza (?:de |do |da )?", "", p.nome) for p in produtos if repositorio.eh_pizza(p)]
            outros = [p.nome for p in produtos if not repositorio.eh_pizza(p)]

            def opcoes(grupo):
                nomes = [t.nome.lower() for t in tamanhos if t.grupo == grupo]
                return _juntar(nomes, "ou").capitalize() + ". " if nomes else ""

            self._dica = ("Pizzas: {}. {}{}. {}"
                          "Pix, dinheiro, crédito e débito. O cliente diz o pedido:").format(
                ", ".join(sabores), opcoes("pizza"), ", ".join(outros), opcoes("refrigerante"))
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
        self._ultima_resposta = "Olá, {}! Seja bem-vindo à pizzaria. {}".format(periodo, FRASE_PEDE_CPF)
        return self._ultima_resposta

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
            return self._cpf_nao_entendido("Não entendi o CPF. Pode repetir os números, por favor?")

        db = self._sessao()
        try:
            cliente = repositorio.buscar_cliente_por_cpf(db, digitos)
        except ValueError:
            # digito verificador nao bate: quase sempre eh o whisper q ouviu um numero errado
            return self._cpf_nao_entendido("Acho que não ouvi direito. Pode repetir o CPF mais devagar?")
        except Exception:
            logger.warning("chamada=%s etapa=buscar_cliente categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        if cliente:
            self._identificar(cliente.id, cliente.nome, cliente.endereco, cliente.telefone)
            return "Oi, {}! Que bom te ver de novo. O que vai querer hoje?".format(self._primeiro_nome())

        self.cadastro = {"cpf": digitos}
        self.etapa = "oferecendo_cadastro"
        return "Não encontrei cadastro com esse CPF. Quer criar agora? É rapidinho."

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
            self._carregar_tamanhos(repositorio.listar_tamanhos(db))
            if eh_consulta(texto) and self._pergunta_de_tamanho(texto):
                fala = self._falar_tamanhos(db)
                if self._duvida_item and self._duvida_item.get("campo") == "tamanho":
                    fala += " " + self._pendencia
                return fala
            return self._montar_pedido_com(db, texto)
        except SQLAlchemyError:
            # erro do llama (ollama fechado) sobe de proposito: o turno_de_voz avisa na tela
            logger.warning("chamada=%s etapa=montar_pedido categoria=banco", self.id_chamada)
            return FRASE_ERRO_BANCO
        finally:
            db.close()

    def _carregar_tamanhos(self, tamanhos):
        """os tamanhos valem como estao no banco agora: o que se entende na fala e o que o atendente oferece."""
        self._vocabulario = tamanhos_do_banco(tamanhos)
        for grupo in {t.grupo for t in tamanhos}:
            # listar_tamanhos ja vem do menor pro maior: "lata, 600 ml ou 2 litros?"
            nomes = [t.nome.lower() for t in tamanhos if t.grupo == grupo]
            self._opcoes_tamanho[grupo] = _juntar(nomes, "ou") + "?"
            if len(nomes) > 1:
                self._exemplos_tamanho[grupo] = "{} e {}".format(_uma(nomes[-1]), _uma(nomes[-2]))

    def _pergunta_de_tamanho(self, texto):
        # "quais tamanhos tem?", "tem pizza grande?": responde com a tabela de tamanhos do banco
        if re.search(r"\btamanhos?\b", _normalizar(texto)):
            return True
        tem = re.search(r"\btem\b", texto, re.IGNORECASE)
        # volume ("tem coca de 2 litros?") continua sendo consulta do produto
        return bool(tem and any(not tamanho[:1].isdigit()
                                for _, tamanho in separar_tamanhos(texto[tem.end():], self._vocabulario)[1]))

    def _montar_pedido_com(self, db, texto):
        normalizado = _normalizar(texto).strip()
        if NAO_SOU_EU.search(normalizado):
            return self._desfazer_identificacao()
        if self._pedindo_endereco:
            return self._receber_novo_endereco(texto)
        if QUER_MUDAR_ENDERECO.search(normalizado):
            if ENDERECO_NA_FALA.search(texto):
                return self._receber_novo_endereco(texto)
            self._pedindo_endereco = True
            return "Claro! Qual é o novo endereço?"
        sem_cortesia = re.sub(r"\bnao( nao)+\b", "nao", " ".join(CORTESIA.sub("", normalizado).split()))
        if self._quer_esvaziar(sem_cortesia):
            return self._esvaziar_pedido()
        conversa = self._fala_sem_pedido(texto, normalizado, sem_cortesia)
        if conversa:
            return conversa
        # "lata, no pix, é só isso" responde o tamanho e fecha: o tamanho não pode se perder no caminho
        responde_tamanho = bool((self._duvida_item or {}).get("campo") == "tamanho" and separar_tamanhos(texto, self._vocabulario)[1])
        if (FIM_DO_PEDIDO.search(sem_cortesia) and not AINDA_NAO_ACABOU.search(texto) and not responde_tamanho
                and not mencoes(texto, repositorio.listar_cardapio(db))[1]):
            self._largar_duvida_de_produto()
            problemas = self._atualizar_pagamento(texto)
            return problemas[0] if problemas else self._fechar_pedido()
        sugestoes, self._sugestoes = self._sugestoes, []
        repetir, self._repetir = self._repetir, None
        # a sugestao termina em pergunta ("quer pedir?"), entao o sim responde a ela e so vale na fala seguinte
        aceitou = normalizado in ACEITES_DA_SUGESTAO or normalizado in RESPOSTAS_VAGAS_A_SUGESTAO
        if (sugestoes or repetir) and sim_ou_nao(texto) is False and len(normalizado.split()) <= 3:
            return "Tudo bem. Quer algo mais?" if self.carrinho else "Tudo bem. O que vai querer?"
        if repetir and aceitou:
            texto = repetir
            normalizado = _normalizar(texto)
        elif sugestoes and aceitou:
            if len(sugestoes) > 1:
                self._sugestoes = sugestoes
                return "Qual você quer: {}?".format(_juntar(sugestoes, "ou"))
            texto = "uma " + sugestoes[0]
            normalizado = _normalizar(texto)
        escolhido = self._resposta_da_ambiguidade(texto)
        if escolhido:
            texto = escolhido
            normalizado = _normalizar(texto)
        if comando_negado(texto):
            self._fechamento_solicitado = False
            self._token_resumo = None
            return "Tudo bem, mantive seu pedido como estava. Quer algo mais?"
        if set(normalizado.split()) & {"taxa", "frete", "gratis", "gratuita", "gratuito",
                                       "prazo", "desconto", "demora"}:
            fala = "A pizzaria precisa confirmar a taxa, o prazo de entrega e se há desconto."
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            self._token_resumo = None
            return fala
        if servico := self._responder_servico(normalizado):
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": servico}])
            self._token_resumo = None
            return servico
        if "?" in texto and ESCOLHE_PAGAMENTO.match(normalizado):
            # "posso pagar no pix?" escolhe o pagamento: a interrogação não faz disso uma consulta
            texto = texto.replace("?", "")
        if eh_consulta(texto):
            self._referencia = None
            self._fechamento_solicitado = False
            self._token_resumo = None
            return self._consultar(db, texto)
        if FECHAR.search(normalizado):
            self._fechamento_solicitado = "nao" not in normalizado.split()
        muda_para = MUDA_PARA.search(normalizado)
        cardapio = repositorio.listar_cardapio(db)
        # "muda a calabresa pra mussarela" ou "muda a calabresa pra pequena": produto antes, produto ou tamanho depois
        sem_tamanho, tamanhos_ditos = separar_tamanhos(texto, self._vocabulario)
        # "troca pra média" sem citar produto muda só o tamanho: quem resolve é o interpretar
        so_tamanho = bool(tamanhos_ditos) and not mencoes(sem_tamanho, cardapio)[1]
        pede_troca = not so_tamanho and bool(PEDIDO_DE_TROCA.search(normalizado) or (
            muda_para and mencoes(muda_para[1], cardapio)[1]
            and (mencoes(muda_para[2], cardapio)[1] or separar_tamanhos(muda_para[2], self._vocabulario)[1])))
        if self._troca_pendente:
            if sem_cortesia in DESISTE_DA_TROCA:
                self._troca_pendente = False
                self._pendencia = self._pendencia_antes_da_troca
                self._pendencia_antes_da_troca = None
                if self._controle:
                    self._controle.definir_pendencia(self._pendencia)
                fala = self._continuar_pedido()
                if fala.startswith("Alteração anotada"):
                    # nada foi alterado: a troca foi abandonada
                    fala = "Tudo bem, mantive seu pedido como estava. Quer algo mais?"
                self.historico.extend([{"role": "user", "content": texto},
                                       {"role": "assistant", "content": fala}])
                return fala
            if not pede_troca:
                return self._esclarecer(self._pendencia)
        if pede_troca:
            if not self._troca_pendente:
                self._pendencia_antes_da_troca = self._pendencia
            self._troca_pendente = True
            self._pendencia = "Pode repetir a troca, informando os produtos e as quantidades?"
            self._token_resumo = None
            if self._controle:
                self._controle.definir_pendencia(self._pendencia)
            self._fala_da_troca = None
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
            if not self._pendencia:
                # trocou a coca por uma pizza: falta saber o tamanho dela
                self._perguntar_tamanho_que_falta()
            fala = self._esclarecer(self._pendencia) if self._pendencia else self._continuar_pedido()
            if self._fala_da_troca and not problemas:
                # diz o que trocou em vez do genérico "Alteração anotada"
                fala = "{} {}".format(self._fala_da_troca, fala.removeprefix("Alteração anotada. "))
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            return fala
        if sem_cortesia in FALAS_DE_FECHAR:
            self._largar_duvida_de_produto()
            return self._fechar_pedido()
        # "nao" responde ao "quer algo mais?". com pergunta pendente, desiste dela e nao fecha nada
        if sem_cortesia in {"nao", "nao quero", "agora nao"}:
            if not self._pendencia:
                return self._fechar_pedido()
            if self._largar_duvida_de_produto():
                return "Tudo bem. Quer algo mais?" if self.carrinho else "Tudo bem. O que vai querer?"
        if confirmacao_explicita(texto):
            if self._pendencia:
                return self._esclarecer(self._pendencia)
            return "Claro! O que mais vai querer?"
        cardapio = repositorio.listar_cardapio(db)

        turno = {"role": "user", "content": texto}
        mensagens = [{"role": "system", "content": self._prompt_do_pedido(cardapio, repositorio.listar_tamanhos(db))}]
        # Uma fala ainda não interpretada impede confirmar o carrinho anterior,
        # inclusive se o Ollama falhar ou devolver uma resposta inválida.
        proposto, duvida, evidencias = interpretar(
            texto, cardapio, self.carrinho, self._duvida_item, self._referencia, self._vocabulario)
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
        # o que muda o pedido eh a evidencia da fala, nunca o json do modelo. entao, se o codigo ja entendeu
        # (item novo, remocao, correcao, pagamento ou duvida), esperar o modelo so custava ate 1 minuto no
        # notebook sem gpu. se nao entendeu, o modelo ainda eh chamado e a falha dele bloqueia o resumo
        resolvida = bool(evidencias or duvida or fala_de_pagamento or endereco_falado)
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
        if not duvida and not problemas:
            # pizza sem tamanho nao tem preco: pergunta antes de seguir, uma pizza por vez
            faltando = [i for i in self.carrinho if self._falta_tamanho(i)]
            if faltando:
                # "Anotei 1 Pizza de Calabresa. Qual o tamanho?" so quando nao tem como confundir a pizza
                curta = (len(faltando) == 1 and len(evidencias) == 1
                         and evidencias[0]["produto"] == faltando[0]["produto"])
                duvida = {"campo": "tamanho", "produto": faltando[0]["produto"], "curta": curta}
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
                fala = self._reconhecer_alteracoes(evidencias) + " Quer algo mais?"
            elif endereco_falado:
                fala = "Certo, a entrega será em {}. Quer algo mais?".format(endereco_falado)
            else:
                fala = "Entendido. Quer algo mais?"
                if fala_de_pagamento and self.pagamento:
                    fala = "Certo, pagamento {}. Quer algo mais?".format(PAGAMENTO_FALADO[self.pagamento])

        self.historico.append({"role": "assistant", "content": fala})
        return fala

    def _fala_sem_pedido(self, texto, normalizado, sem_cortesia):
        """cumprimento, "quero pedir", "um momento", "obrigado": responde e deixa o pedido como esta."""
        if PEDE_TEMPO.fullmatch(sem_cortesia) or HESITACAO.fullmatch(sem_cortesia):
            return "Sem pressa. Quando decidir, é só falar."
        if SO_CUMPRIMENTO.fullmatch(sem_cortesia) or (
                "?" in texto and sem_cortesia in {"tudo bem", "tudo bom", "como vai"}):
            inicio = "Olá!"
        elif SO_QUER_PEDIR.fullmatch(sem_cortesia):
            inicio = "Claro!"
        elif normalizado and not sem_cortesia:
            # so agradeceu
            inicio = "De nada!"
        elif sem_cortesia in SO_CONCORDA and not (
                (self._sugestoes or self._repetir) and sem_cortesia in RESPOSTAS_VAGAS_A_SUGESTAO):
            # "tá" depois de "quer pedir?" aceita a sugestão; sem pergunta assim, só concorda
            inicio = ""
        elif sem_cortesia in DEIXA_PRA_LA and not self._pendencia_firme():
            # "esquece": larga a dúvida vaga ("não entendi o produto"); pergunta de tamanho continua
            self._largar_duvida_de_produto()
            self._sugestoes = []
            inicio = "Tudo bem."
        else:
            return None
        # a pergunta que estava aberta continua valendo, sem contar como fala nao entendida.
        # "nao entendi o produto" nao eh pergunta aberta: repetir depois de um "oi" soaria como bronca
        return "{} {}".format(inicio, (self._pendencia if self._pendencia_firme() else None) or (
            "Quer algo mais?" if self.carrinho else "O que vai querer?")).strip()

    def _responder_servico(self, normalizado):
        """"aceita cartão?", "tem entrega?", "que horas fecham?": resposta fixa, sem o modelo. None se não for isso."""
        seguir = " " + (self._pendencia if self._pendencia_firme() else
                        "Quer algo mais?" if self.carrinho else "O que vai querer?")
        if PERGUNTA_DE_PAGAMENTO.search(normalizado):
            outro = PAGAMENTO_QUE_NAO_ACEITA.search(normalizado)
            if outro:
                return "Não aceitamos {}. Pode ser {}.".format(
                    NOMES_DE_PAGAMENTO.get(outro.group(), outro.group()), FORMAS_ACEITAS) + seguir
            return "Aceitamos, sim. Pode ser {}.".format(FORMAS_ACEITAS) + seguir
        if PERGUNTA_DE_ENTREGA.search(normalizado) and not ENDERECO_NA_FALA.search(normalizado):
            if ENTREGA_EM_LUGAR.search(normalizado):
                return "Fazemos entrega, sim. Se o endereço está na área de entrega, a pizzaria confirma." + seguir
            endereco = self.endereco_entrega or self.endereco_do_cadastro
            return "Fazemos entrega, sim{}.".format(", em " + endereco if endereco else "") + seguir
        if PERGUNTA_DE_HORARIO.search(normalizado):
            return "A pizzaria precisa confirmar o horário de funcionamento." + seguir
        return None

    def _pendencia_firme(self):
        """Pergunta que ainda vale repetir: tamanho, quantidade... não o "não entendi o produto"."""
        duvida = self._duvida_item or {}
        vaga = duvida.get("campo") in {"produto", "intencao", "fora_do_pedido"} and not duvida.get("candidatos")
        return bool(self._pendencia) and not vaga

    def _quer_esvaziar(self, normalizado):
        if NAO_ESVAZIAR.search(normalizado):
            return False
        return bool(ESVAZIAR_PEDIDO.search(normalizado)
                    or (normalizado in SO_CANCELAR and not self._troca_pendente))

    def _esvaziar_pedido(self):
        tinha_itens = bool(self.carrinho)
        self._limpar_pedido()
        self.historico = []
        if not tinha_itens:
            return "Seu pedido já está vazio. O que vai querer?"
        return "Tudo bem, esvaziei o seu pedido. Nada foi registrado. O que vai querer?"

    def _receber_novo_endereco(self, texto):
        desistiu = sim_ou_nao(texto) is False and len(_normalizar(texto).split()) <= 3
        rua = ENDERECO_NA_FALA.search(texto)
        endereco = None if desistiu else extrair_endereco(FIM_DO_ENDERECO.sub("", rua.group() if rua else texto))
        if not endereco and not desistiu:
            self._pedindo_endereco = True
            return "Não entendi o endereço. Pode falar a rua e o número?"
        self._pedindo_endereco = False
        if endereco:
            self.endereco_entrega = endereco
        if self._fechamento_solicitado:
            return self._fechar_pedido()
        if desistiu:
            return "Tudo bem, mantive o endereço. Quer algo mais?"
        return "Certo, a entrega será em {}. Quer algo mais?".format(endereco)

    def _largar_duvida_de_produto(self):
        """
        desiste de um item que nem entrou no pedido, pra pessoa nunca ficar presa nele.
        correcao que falhou nao passa por aqui: essa continua bloqueando o resumo ate ser resolvida.
        """
        if not self._pendencia or not self._duvida_item:
            return False
        if self._duvida_item.get("campo") not in {"produto", "fora_do_pedido"}:
            return False
        self._pendencia = self._duvida_item = self._ultima_pergunta = None
        self._tentativas = 0
        if self._controle:
            self._controle.definir_pendencia(None)
        return True

    def _resposta_da_ambiguidade(self, texto):
        """
        "qual agua: com gas ou mineral?" -> "com gas". a resposta so traz o que diferencia as opcoes,
        e sozinha nao bate com nenhum nome inteiro do cardapio. vira "1 Agua com Gas 500ml" e segue
        pelas mesmas validacoes de qualquer pedido falado.
        """
        duvida = self._duvida_item or {}
        candidatos = duvida.get("candidatos") or []
        if duvida.get("campo") != "produto" or len(candidatos) < 2 or eh_consulta(texto):
            return None

        def palavras_de(nome):
            return {p.removesuffix("s") for p in _normalizar(nome).split()}

        enchimento = {"a", "o", "de", "da", "do", "uma", "um", "quero", "pode", "ser", "essa", "esse", "e",
                      "isso", "aquela", "aquele", "mesmo", "por", "favor", "sim", "pra", "mim"}
        falado = palavras_de(texto) - enchimento
        if not falado:
            return None
        sem = re.search(r"\bsem (\w+)", _normalizar(texto))
        escolhas = []
        for nome in candidatos:
            minhas = palavras_de(nome)
            outras = set().union(*(palavras_de(c) for c in candidatos if c != nome))
            if sem:
                # "sem gas" escolhe a unica opcao que nao tem gas no nome
                if sem[1].removesuffix("s") not in minhas and falado <= minhas | {"sem", sem[1].removesuffix("s")}:
                    escolhas.append(nome)
            elif falado <= minhas and falado & (minhas - outras):
                escolhas.append(nome)
        if len(escolhas) != 1:
            return None
        return "{} {}".format(duvida.get("quantidade") or 1, escolhas[0])

    def _falta_tamanho(self, item):
        return item["produto"] in self._grupos and not item.get("tamanho")

    def _opcoes(self, produto):
        grupo = self._grupos.get(produto, "pizza")
        return self._opcoes_tamanho.get(grupo, FRASE_PEDE_TAMANHO)

    def _reconhecer_alteracoes(self, evidencias):
        verbos = {"adicionar": "Anotei", "remover": "Tirei", "corrigir": "Ajustei para", "tamanho": "Certo,"}
        return " ".join("{} {} {}{}.".format(verbos[e["acao"]], e["quantidade"],
                                              _com_tamanho(e["produto"], e.get("tamanho")),
                        " ({})".format(e["observacao"]) if e.get("observacao") else "") for e in evidencias)

    def _pergunta_do_campo(self, duvida):
        if not duvida:
            return "Não consegui interpretar essa alteração. Pode repetir o produto e a quantidade?"
        campo = duvida["campo"]
        if campo == "quantidade":
            return "Quantas unidades inteiras{} você quer?".format(
                " de " + duvida["produto"] if duvida.get("produto") else "")
        if campo == "observacao":
            return "Qual é a observação para {}?".format(duvida["produto"])
        if campo == "fora_do_pedido":
            return "{} não está no seu pedido. Quer algo mais?".format(duvida["produto"])
        if campo == "tamanho":
            produto = duvida["produto"]
            if duvida.get("misto"):
                return "Quantas de cada tamanho? Por exemplo: {}.".format(
                    self._exemplos_tamanho.get(self._grupos.get(produto, "pizza"), EXEMPLO_DE_TAMANHOS["pizza"]))
            if duvida.get("indisponivel"):
                return "Não temos esse tamanho. {} pode ser {}".format(_com_artigo(produto), self._opcoes(produto))
            if duvida.get("curta"):
                return "Qual o tamanho: " + self._opcoes(produto)
            return "Qual o tamanho {}: {}".format(_da(produto), self._opcoes(produto))
        if campo == "intencao":
            return "Não entendi. Pode repetir o que você quer?"
        if campo == "qual_observacao":
            if not duvida["itens"]:
                return "Seu pedido ainda está vazio. Qual produto você quer {}?".format(duvida["observacao"])
            return "Qual item fica {}? Diga, por exemplo: {} {}.".format(
                duvida["observacao"], _com_artigo(duvida["itens"][0]).lower(), duvida["observacao"])
        if campo == "qual_item":
            if not duvida["itens"]:
                return "Seu pedido ainda está vazio. O que vai querer?"
            return "Qual delas: {}?".format(_juntar([_com_artigo(n).lower() for n in duvida["itens"]], "ou"))
        if campo == "qual_muda":
            para, quantidade = duvida["para"], duvida.get("quantidade")
            if not duvida["itens"]:
                if quantidade:
                    return "Seu pedido ainda está vazio. O que vai querer?"
                return "Nenhum item do seu pedido tem o tamanho {}. Quer algo mais?".format(para)
            item = _com_artigo(duvida["itens"][0]).lower()
            exemplo = "muda {} para {}".format(item, para) if quantidade else "{} é {}".format(item, para)
            return "Qual item muda para {}? Diga, por exemplo: {}.".format(para, exemplo)
        candidatos = duvida.get("candidatos", [])
        if duvida.get("nao_encontrado"):
            # frase longa nao eh nome de produto: repetir ela de volta soa como erro de maquina
            if len(duvida["nao_encontrado"].split()) > 4:
                return "Não entendi. Pode repetir o que você quer?"
            return "Não temos {} no cardápio. Quer escolher outra opção?".format(duvida["nao_encontrado"])
        if candidatos:
            if len(candidatos) <= 4:
                return "Qual produto você quer: {}?".format(_juntar(candidatos, "ou"))
            return "Claro! Qual sabor você quer?"
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
            return "Desculpe, não entendi. " + pergunta
        return "Desculpe, ainda não entendi. Pode falar de outro jeito? " + pergunta

    def _continuar_pedido(self):
        if self._pendencia:
            return self._esclarecer(self._pendencia)
        return self._fechar_pedido() if self._fechamento_solicitado else "Alteração anotada. Quer algo mais?"

    def _falar_tamanhos(self, db):
        tamanhos = repositorio.listar_tamanhos(db)
        if not tamanhos:
            return "Não consegui consultar os tamanhos agora."
        frases = []
        pizzas = ["{}, com {} fatias".format(t.nome, t.fatias) for t in tamanhos if t.grupo == "pizza"]
        if pizzas:
            frases.append("As pizzas podem ser {}.".format(_juntar(pizzas)))
        bebidas = [t.nome.lower() for t in tamanhos if t.grupo == "refrigerante"]
        if bebidas:
            frases.append("Os refrigerantes vêm em {}.".format(_juntar(bebidas, "ou")))
        return " ".join(frases)

    def _precos_por_tamanho(self, produto, tamanhos, so=None):
        # o cardapio guarda o preco do maior tamanho; os outros saem do desconto de cada tamanho
        grupo = repositorio.grupo_tamanho(produto)
        tamanhos = [t for t in tamanhos if t.grupo == grupo]
        escolhidos = [t for t in tamanhos if t.nome == so]
        if so and escolhidos:
            return "{} custa {}.".format(_com_artigo(_com_tamanho(produto.nome, so)),
                                         preco_falado(repositorio.preco_no_tamanho(produto, escolhidos[0])))
        precos = ["{} a {}".format(preco_falado(repositorio.preco_no_tamanho(produto, t)), t.nome.lower())
                  for t in sorted(tamanhos, key=lambda t: t.desconto)]
        return "{} custa {}.".format(_com_artigo(produto.nome), _juntar(precos))

    def _consultar(self, db, texto):
        produtos = repositorio.listar_cardapio(db)
        normalizado = _normalizar(texto)
        # "quanto custa a pizza grande de calabresa": o tamanho sai antes de procurar o nome
        sem_tamanho, tamanhos_ditos = separar_tamanhos(texto, self._vocabulario)
        palavras, citados = mencoes(sem_tamanho, produtos)
        if RECLAMA_DO_PEDIDO.search(normalizado):
            fala = self._falar_pedido_atual(" O que você quer mudar?")
        elif CONSULTA_PEDIDO_ATUAL.search(normalizado) or (PERGUNTA_DO_TOTAL.search(normalizado) and not citados):
            fala = self._falar_pedido_atual(" Quer algo mais?")
        elif CONSULTA_HISTORICO.search(normalizado):
            fala = self._falar_historico(db, normalizado)
        elif CONSULTA_RECOMENDACAO.search(normalizado):
            fala = self._recomendar(db, normalizado, produtos)
        elif cardapio_completo(texto):
            if not produtos:
                fala = "Não há produtos disponíveis no cardápio neste momento."
            elif re.search(r"\b(?:todos|todas|completo|inteiro|precos)\b", normalizado):
                todos = repositorio.listar_tamanhos(db)
                # o preco do cardapio eh o do tamanho sem desconto de cada grupo
                maiores = {t.grupo: t.nome.lower() for t in todos if not t.desconto}
                precos_de = [frase.format(maiores[grupo]) for grupo, frase in (
                    ("pizza", "as pizzas no tamanho {}"), ("refrigerante", "os refrigerantes de {}")) if grupo in maiores]
                fala = "Cardápio completo{}. ".format(", com " + " e ".join(precos_de) if precos_de else "") + " ".join(
                    "{}: {}.".format(p.nome, preco_falado(p.preco)) for p in produtos)
                tamanhos = sorted((t for t in todos if t.desconto),
                                  key=lambda t: (t.grupo != "pizza", t.desconto))
                if tamanhos:
                    fala += " " + " ".join("{} {}: {} a menos.".format(
                        "Pizza" if t.grupo == "pizza" else "Refrigerante", t.nome.lower(), preco_falado(t.desconto))
                        for t in tamanhos)
            else:
                # ler 18 produtos em voz alta cansa: fala as categorias e deixa a pessoa escolher
                fala = "Temos {}. O que você quer saber?".format(_juntar(_categorias_faladas(produtos)))
        elif re.search(r"\b(?:preco|precos|custa|custam|quanto)\b", normalizado) and citados:
            unicos, aviso = self._produtos_da_consulta(normalizado, palavras, citados)
            tamanhos = repositorio.listar_tamanhos(db)
            so = tamanhos_ditos[0][1] if len({t for _, t in tamanhos_ditos}) == 1 else None
            fala = aviso or " ".join(
                self._precos_por_tamanho(p, tamanhos, so)
                if any(t.grupo == repositorio.grupo_tamanho(p) for t in tamanhos) else
                "{} custa {}.".format(_com_artigo(p.nome), preco_falado(p.preco))
                for p in unicos)
        elif re.search(r"\b(?:ingredientes|contem|leva|tem cebola)\b", normalizado) and citados:
            unicos, aviso = self._produtos_da_consulta(normalizado, palavras, citados)
            fala = aviso or " ".join("{}: {}.".format(p.nome, p.descricao or "ingredientes não informados")
                                     for p in unicos)
        elif disponivel := self._falar_se_tem(db, normalizado, palavras, citados):
            fala = disponivel
        elif (self._categoria_citada(normalizado) and not any(len(c) == 1 for _, _, c in citados)
              and re.search(r"\b(?:quais|qual|que|tem|opcoes|sabores|vendem)\b", normalizado)):
            categoria = self._categoria_citada(normalizado)
            nomes = [p.nome for p in repositorio.listar_cardapio(db, categoria)]
            fala = ("Temos {}. Quer saber o preço de alguma opção?".format(_juntar(nomes)) if nomes
                    else "Não temos opções de {} disponíveis agora.".format(categoria))
        elif (fora := TEM_FORA_DO_CARDAPIO.fullmatch(normalizado.strip())) and not citados and not (
                set(fora[1].split()) & NAO_E_ITEM):
            # "tem cerveja?": nada do cardápio depois do verbo. O modelo levava até 1 minuto e podia inventar
            fala = "Não temos {} no cardápio. Temos {}.".format(fora[1], _juntar(_categorias_faladas(produtos)))
        else:
            mensagens = [{"role": "system", "content": self._prompt_do_pedido(
                produtos, repositorio.listar_tamanhos(db))}] + self.historico + [
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

    def _produtos_da_consulta(self, normalizado, palavras, citados):
        """
        de quais produtos a pessoa quer saber. devolve (produtos, aviso): o aviso vem quando a fala nao
        aponta um produto ("a pizza de sushi", "a pizza"), pra nao ler o cardapio inteiro em voz alta.
        """
        categoria = self._categoria_citada(normalizado)
        da_categoria = set(categoria.split()) if categoria else set()
        produtos = {}
        for indice, (inicio, fim, candidatos) in enumerate(citados):
            if len(candidatos) > 1:
                seguinte = citados[indice + 1][0] if indice + 1 < len(citados) else len(palavras)
                depois = [p for p in palavras[fim:seguinte] if p not in {"por", "favor", "hoje", "mesmo", "ai"}]
                trecho = " ".join(palavras[inicio:fim])
                # "pizza de sushi": o que sobrou depois do nome nao eh do cardapio nem palavra da pergunta
                if any(p.rstrip("s") not in da_categoria and p not in PALAVRAS_DA_CONSULTA and not p.isdigit()
                       for p in depois):
                    return [], "Não temos {} no cardápio. Quer saber de outra opção?".format(
                        " ".join([trecho] + depois))
                if categoria:
                    candidatos = [p for p in candidatos if categoria in _normalizar(p.categoria)] or candidatos
                if len(candidatos) > 4:
                    rotulo = categoria or re.sub(r"\s+d[eao]$", "", trecho)
                    nomes = ": " + _juntar([p.nome for p in candidatos]) if len(candidatos) <= 8 else ""
                    return [], "Temos {} opções de {}{}. De qual você quer saber?".format(
                        len(candidatos), rotulo, nomes)
            produtos.update((p.id, p) for p in candidatos)
        return list(produtos.values()), None

    def _falar_se_tem(self, db, normalizado, palavras, citados):
        """
        "tem pizza de calabresa?", "voces vendem coca?": responde pelo cardapio. so quando o produto vem
        logo depois do verbo, pq "a calabresa tem cebola?" pergunta do ingrediente. None quando nao eh o caso.
        """
        verbo = next((i for i, p in enumerate(palavras) if p in {"tem", "teria", "vende", "vendem"}), None)
        if verbo is None or not citados or citados[0][0] < verbo:
            return None
        if any(p not in {"a", "o", "as", "os", "um", "uma", "de", "da", "do", "ai", "la", "alguma", "algum", "tambem"}
               for p in palavras[verbo + 1:citados[0][0]]):
            return None
        produtos, aviso = self._produtos_da_consulta(normalizado, palavras, citados)
        if aviso:
            # "tem pizza?" segue pra lista da categoria; "tem pizza de sushi?" ja tem resposta
            return aviso if aviso.startswith("Não temos") else None
        if len(produtos) > 1:
            return "Temos {}. Quer saber o preço de alguma opção?".format(_juntar([p.nome for p in produtos]))
        produto = produtos[0]
        tamanhos = repositorio.listar_tamanhos(db)
        if any(t.grupo == repositorio.grupo_tamanho(produto) for t in tamanhos):
            preco = self._precos_por_tamanho(produto, tamanhos)
        else:
            preco = "{} custa {}.".format(_com_artigo(produto.nome), preco_falado(produto.preco))
        # o sim na fala seguinte pede o produto, igual a uma sugestao aceita
        self._sugestoes = [produto.nome]
        return "Temos, sim. {} Quer pedir?".format(preco)

    def _falar_pedido_atual(self, complemento):
        if not self.carrinho:
            return "Ainda não anotei nada neste pedido. O que vai querer?"
        itens = ["{} {}".format(i["quantidade"], _com_tamanho(i["produto"], i.get("tamanho"))) for i in self.carrinho]
        total = sum((i["preco"] * i["quantidade"] for i in self.carrinho), Decimal("0.00"))
        return "Até agora anotei {}, subtotal de {}.".format(_juntar(itens), preco_falado(total)) + complemento

    def _falar_historico(self, db, normalizado):
        # com pedido em andamento, "o que eu pedi" sem falar do passado eh sobre o pedido de agora
        fala_do_passado = re.search(r"\b(?:ultim\w+|anterior\w*|passad\w+|historico|meus pedidos|ja pedi)\b",
                                    normalizado)
        if self.carrinho and not fala_do_passado:
            return self._falar_pedido_atual(" Quer algo mais?")

        # so le pelo cliente_id desta chamada: o historico de outra pessoa nunca entra aqui
        if not self.cliente_id:
            return "Sem uma conta, eu não tenho histórico de pedidos para consultar."

        varios = re.search(r"\b(?:pedidos|compras|historico)\b", normalizado)
        pedidos = repositorio.historico_cliente(db, self.cliente_id, limite=3 if varios else 1)
        if not pedidos:
            return "Você ainda não tem pedidos anteriores."

        def nome_do_item(item):
            return _com_tamanho(item.produto.nome, item.tamanho.nome if item.tamanho else None)

        def descrever(pedido):
            itens = ["{} {}".format(i.quantidade, nome_do_item(i)) for i in pedido.itens]
            return "em {}: {}, total de {}.".format(
                pedido.criado_em.astimezone().strftime("%d/%m"), _juntar(itens) or "sem itens registrados",
                preco_falado(pedido.total))

        if len(pedidos) == 1:
            itens = ["{} {}".format(i.quantidade, nome_do_item(i)) for i in pedidos[0].itens]
            if not itens:
                return "Seu último pedido foi " + descrever(pedidos[0])
            # o sim na fala seguinte repete: passa pelas mesmas validacoes de um pedido falado
            self._repetir = " e ".join(itens)
            return "Seu último pedido foi " + descrever(pedidos[0]) + " Quer pedir de novo?"
        return "Seus últimos {} pedidos foram: {} Se quiser repetir algum, me diga os produtos.".format(
            len(pedidos), " ".join(descrever(p) for p in pedidos))

    def _categoria_citada(self, normalizado):
        # "quais bebidas voce indica" vira "bebida", igual a busca por categoria do cardapio
        singular = " ".join(p.rstrip("s") for p in normalizado.split())
        categoria = next((c for c in ("pizza doce", "pizza salgada", "pizza", "bebida", "sobremesa", "borda")
                          if re.search(r"\b" + c + r"\b", singular)), None)
        if categoria:
            return categoria
        return next((SINONIMOS_DE_CATEGORIA[p] for p in singular.split() if p in SINONIMOS_DE_CATEGORIA), None)

    def _recomendar(self, db, normalizado, produtos):
        categoria = self._categoria_citada(normalizado)
        convite = " Quer pedir?"

        favoritos = []
        # "o que mais sai da casa" pergunta da pizzaria, nao do cliente
        if self.cliente_id and "casa" not in normalizado.split():
            favoritos = repositorio.itens_mais_pedidos_do_cliente(db, self.cliente_id, 1, categoria)
        if favoritos:
            produto = favoritos[0][0]
            self._sugestoes = [produto.nome]
            maior = next((t.nome.lower() for t in repositorio.listar_tamanhos(db, repositorio.grupo_tamanho(produto))
                          if not t.desconto), None) if repositorio.grupo_tamanho(produto) else None
            return "Você costuma pedir {}, que está {}{}.".format(
                produto.nome, preco_falado(produto.preco), " a " + maior if maior else "") + convite

        # cliente novo, sem conta ou sem nada daquela categoria: vale o que a casa mais vende
        campeoes = repositorio.itens_mais_pedidos_da_casa(db, 2, categoria)
        if campeoes:
            nomes = [produto.nome for produto, _ in campeoes]
            self._sugestoes = nomes
            if len(nomes) > 1:
                return "Os mais pedidos da casa são {}. Qual você prefere?".format(_juntar(nomes))
            return "O mais pedido da casa é {}.".format(nomes[0]) + convite

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
        # "não, troca a calabresa": com a virgula o nao responde a pergunta anterior e a troca vale.
        # sem ela ("não troque a coca") continua sendo uma negacao, e nada muda
        nao_solto = re.match(r"\s*n[aã]o\s*[,.;!]", texto, re.IGNORECASE)
        texto = re.sub(r"\s+por favor$", "", _normalizar(texto))
        if nao_solto:
            texto = re.sub(r"^nao\s+", "", texto)
        inicio = (r"(?:(?:sim|nao)\s+mas\s+|sim\s+|na verdade\s+|entao\s+|ah\s+|olha\s+)*"
                  r"(?:(?:pode|quero|queria|gostaria de)\s+)?")
        em_vez = r"(?:em vez|ao inves|no lugar) d[eao]s?"
        pedir = r"(?:eu\s+)?(?:quero|queria|vou querer|coloca|coloque|bota|bote|poe|ponha|manda|mande|me ve|pode ser)"
        # as tres formas dizem a mesma coisa: (padrao, quem sai, quem entra)
        formas = [
            # "troca a calabresa por uma mussarela", "muda a calabresa pra mussarela"
            (r"(?:troque|trocar|troca|substitua|substituir|substitui|mude|mudar|muda|altere|alterar|altera)\s+(.+?)"
             r"\s+(?:por|pela|pelo|pelas|pelos|pra|para)\s+(.+)", 1, 2),
            # "em vez da calabresa quero uma mussarela"
            (em_vez + r"\s+(.+?)\s+" + pedir + r"\s+(.+)", 1, 2),
            # "em vez da calabresa, uma mussarela": sem verbo, a quantidade marca onde comeca o que entra
            (em_vez + r"\s+(.+?)\s+((?:uma?|duas|dois|tres|\d+)\s+.+)", 1, 2),
            # "quero uma mussarela no lugar da calabresa"
            (r"(?:" + pedir + r"\s+)?(.+?)\s+" + em_vez + r"\s+(.+)", 2, 1),
        ]
        partes = next(((achado[sai], achado[entra]) for padrao, sai, entra in formas
                       if (achado := re.fullmatch(inicio + padrao, texto))), None)
        if not partes or not self._controle or not self._controle.itens:
            return ["Pode dizer qual produto deseja trocar e por qual produto, com as quantidades?"]
        # "troque a calabresa grande por uma mussarela media": o tamanho nao faz parte do nome
        lado_origem, tamanhos_origem = separar_tamanhos(partes[0], self._vocabulario)
        lado_destino, tamanhos_destino = separar_tamanhos(partes[1], self._vocabulario)
        # "as calabresas", "o tamanho das calabresas": no plural, a mudanca de tamanho vale para todas
        todas = bool(re.match(r"(?:(?:o\s+)?tamanho\s+d)?[ao]s\s", lado_origem))
        lado_origem = re.sub(r"^(?:o\s+)?tamanho\s+d[aeo]s?\s+", "", lado_origem)
        retirar, origem = _item_da_troca(lado_origem)
        acrescentar, destino = _item_da_troca(lado_destino)
        origem, destino = _nome_na_troca(origem), _nome_na_troca(destino)
        tamanho_origem = tamanhos_origem[0][1] if tamanhos_origem else None
        tamanho_destino = tamanhos_destino[0][1] if tamanhos_destino else None
        if TAMANHO_INDISPONIVEL in (tamanho_origem, tamanho_destino):
            return ["Não temos esse tamanho. Pode repetir a troca com um tamanho do cardápio?"]
        itens = [i for i in self._controle.itens
                 if origem and f" {origem} " in f" {_nome_na_troca(i.nome)} "
                 and (tamanho_origem is None or i.tamanho == tamanho_origem)]
        if len(itens) != 1:
            return ["Qual item do pedido você deseja trocar? Informe também a quantidade."]
        item = itens[0]
        # "troca a calabresa grande por uma média": do outro lado so veio o tamanho, o produto fica
        so_tamanho = not destino and tamanho_destino is not None
        if retirar is None:
            if item.quantidade != 1 and not (so_tamanho and todas):
                return ["Quantas unidades de {} deseja trocar?".format(item.nome)]
            retirar = item.quantidade
        if so_tamanho:
            produtos = [p for p in repositorio.listar_cardapio(db) if p.id == item.produto_id]
            if produtos and not repositorio.grupo_tamanho(produtos[0]):
                return ["{} tem tamanho único.".format(_com_artigo(item.nome))]
            if produtos and not self._vocabulario.serve_para(tamanho_destino, produtos[0]):
                return ["{} não tem esse tamanho. Pode ser {}".format(_com_artigo(item.nome), self._opcoes(item.nome))]
            acrescentar = acrescentar or retirar
        else:
            produtos = [p for p in repositorio.listar_cardapio(db)
                        if destino and f" {destino} " in f" {_nome_na_troca(p.nome)} "]
        if not produtos:
            return ["Não temos esse produto no cardápio ou a troca contém mais de uma alteração. "
                    "Pode repetir uma troca por vez, com os nomes e as quantidades?"]
        if len(produtos) > 1:
            return [self._pergunta_de_ambiguidade(destino, produtos)]
        if acrescentar is None:
            # "troca a calabresa por mussarela" eh uma por uma; saindo mais de uma, pergunta
            if retirar != 1:
                return ["Quantas unidades de {} deseja acrescentar na troca?".format(produtos[0].nome)]
            acrescentar = 1
        # trocar de sabor mantem o tamanho da pizza que saiu; "mais uma margherita" eh igual a que ja
        # esta no pedido. sem nenhum dos dois, a pizza entra sem tamanho e o atendente pergunta
        # (coca de 2 litros por guarana continua 2 litros; coca por pizza pergunta o tamanho da pizza)
        novo_tamanho = ""
        grupo = repositorio.grupo_tamanho(produtos[0])
        if grupo:
            dito = tamanho_destino if self._vocabulario.do_grupo(tamanho_destino, grupo) else ""
            herdado = item.tamanho if self._grupos.get(item.nome) == grupo else ""
            iguais = {i.tamanho for i in self._controle.itens if i.produto_id == produtos[0].id and i.tamanho}
            novo_tamanho = dito or herdado or (iguais.pop() if len(iguais) == 1 else "")
        controle = deepcopy(self._controle)
        try:
            # mudar so o tamanho nao eh outro produto: a observacao ("sem cebola") continua valendo
            controle.substituir(item.id, retirar, produtos[0].id, acrescentar, tamanho=novo_tamanho or "",
                                observacao=item.observacao if so_tamanho else "")
        except ErroPedido as erro:
            return [str(erro)]
        if so_tamanho:
            self._fala_da_troca = "Certo, {} {}.".format(acrescentar, _com_tamanho(item.nome, novo_tamanho or None))
        else:
            self._fala_da_troca = "Troquei {} {} por {} {}.".format(
                retirar, _com_tamanho(item.nome, item.tamanho or None),
                acrescentar, _com_tamanho(produtos[0].nome, novo_tamanho or None))
        return self._atualizar_carrinho(db, [
            {"produto": i.nome, "quantidade": i.quantidade, "observacao": i.observacao,
             "tamanho": i.tamanho or None}
            for i in controle.itens
        ])

    def _atualizar_carrinho(self, db, itens):
        """
        Valida o retrato completo antes de substituir o carrinho.
        Uma falha preserva os itens anteriores e exige esclarecimento.
        """
        novo = []
        problemas = []
        todos_tamanhos = repositorio.listar_tamanhos(db)
        tamanhos = {(t.grupo, _normalizar(t.nome)): t for t in todos_tamanhos}

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

            # pizza e refrigerante tem tamanho. sem tamanho ainda, o item entra e o atendente pergunta
            tamanho = None
            grupo = repositorio.grupo_tamanho(produto)
            if grupo and item.get("tamanho"):
                tamanho = tamanhos.get((grupo, _normalizar(item["tamanho"])))
                if tamanho is None:
                    problemas.append("Qual o tamanho {}: {}".format(
                        _da(produto.nome), self._opcoes_tamanho.get(grupo, FRASE_PEDE_TAMANHO)))
                    continue

            repetido = next((i for i in novo if i["produto"] == produto.nome
                             and i["observacao"] == observacao
                             and i["tamanho"] == (tamanho.nome if tamanho else None)), None)
            if repetido:
                repetido["quantidade"] += quantidade
            else:
                novo.append({
                    "produto": produto.nome,
                    "quantidade": quantidade,
                    "preco": repositorio.preco_no_tamanho(produto, tamanho),
                    "observacao": observacao,
                    "tamanho": tamanho.nome if tamanho else None,
                })

        # Uma extração incompleta nunca substitui parte do pedido anterior.
        if not problemas:
            cardapio = repositorio.listar_cardapio(db)
            controle = ControlePedido([
                ProdutoCardapio(p.id, p.nome, Decimal(str(p.preco)))
                for p in cardapio
            ])
            for item in novo:
                produto = repositorio.buscar_produtos(db, item["produto"])[0]
                controle.adicionar(produto.id, item["quantidade"], item["observacao"] or "",
                                   tamanho=item["tamanho"] or "", preco=item["preco"])
            self.carrinho = novo
            self._controle = controle
            self._grupos = {p.nome: repositorio.grupo_tamanho(p) for p in cardapio if repositorio.grupo_tamanho(p)}
            self._carregar_tamanhos(todos_tamanhos)
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
                return ["Crédito ou débito?"]
            return [FRASE_PEDE_PAGAMENTO]

    def _perguntar_tamanho_que_falta(self):
        """pizza sem tamanho nao tem preco: vira a pendencia do pedido, uma pizza por vez."""
        sem_tamanho = next((i for i in self.carrinho if self._falta_tamanho(i)), None)
        if not sem_tamanho:
            return False
        self._duvida_item = {"campo": "tamanho", "produto": sem_tamanho["produto"]}
        self._pendencia = self._pergunta_do_campo(self._duvida_item)
        if self._controle:
            self._controle.definir_pendencia(self._pendencia)
        return True

    def _fechar_pedido(self):
        # so le o resumo quando nao falta nada: o cliente confirma o pedido inteiro de uma vez
        if not self._pendencia:
            self._perguntar_tamanho_que_falta()
        if self._pendencia:
            if self._duvida_item and self._duvida_item.get("campo") == "tamanho":
                # quem pediu pra fechar ouve o resumo logo depois de dizer o tamanho
                self._fechamento_solicitado = True
                produto = self._duvida_item["produto"]
                return "Antes de fechar, qual o tamanho {}: {}".format(_da(produto), self._opcoes(produto))
            return self._esclarecer(self._pendencia)
        if not self.carrinho:
            # vale também pra quem tirou o último item na confirmação
            self._fechamento_solicitado = False
            return "Seu pedido está vazio. O que vai querer?"
        # quem ja pediu pra fechar nao precisa pedir de novo depois de dizer como paga
        self._fechamento_solicitado = True
        if not self.pagamento:
            return FRASE_PEDE_PAGAMENTO
        if not (self.endereco_entrega or self.endereco_do_cadastro):
            self._pedindo_endereco = True
            return "Qual é o endereço para entrega?"
        self.etapa = "confirmando_pedido"
        return self._resumo_do_pedido()

    def _resumo_do_pedido(self):
        resumo = self._controle.resumir()
        self._token_resumo = resumo.token
        itens = ["{} {}{}".format(i.quantidade, _com_tamanho(i.nome, i.tamanho),
                 " (solicitação: {})".format(i.observacao) if i.observacao else "")
                 for i in resumo.itens]
        return ("Seu pedido ficou assim: {}. Total de {}, entrega em {}, "
                "pagamento {}. Posso confirmar?").format(
            _juntar(itens),
            preco_falado(resumo.subtotal),
            self.endereco_entrega or self.endereco_do_cadastro,
            PAGAMENTO_FALADO[self.pagamento],
        )

    def _fala_solta_na_confirmacao(self, texto):
        """palavra que o whisper errou nao pode virar "nao temos X": a pergunta aqui eh sim ou nao."""
        normalizado = _normalizar(texto).strip()
        palavras = set(normalizado.split())
        if "?" in texto or len(palavras) > 2 or sim_ou_nao(texto) is False:
            return False
        if self._quer_esvaziar(normalizado):
            return False
        # no pix, endereco novo e "tira a coca" sao mudancas no pedido, nao falas soltas
        if palavras & (set(repositorio.SINAIS_DE_PAGAMENTO) | {"cartao", "maquininha", "endereco", "entrega", "rua",
                                                               "avenida", "tira", "tire", "troca", "troque"}):
            return False
        db = self._sessao()
        try:
            cardapio = repositorio.listar_cardapio(db)
        finally:
            db.close()
        if mencoes(texto, cardapio)[1]:
            return False
        # "mais uma", "sem cebola": sem produto, mas mudam o pedido (ou perguntam qual item)
        _, duvida, evidencias = interpretar(texto, cardapio, self.carrinho, None, self._referencia, self._vocabulario)
        return not evidencias and (duvida or {}).get("campo") not in {"qual_item", "qual_observacao", "qual_muda"}

    def _receber_confirmacao_do_pedido(self, texto):
        if not (confirmacao_explicita(texto) or parece_confirmacao(texto) or confirmacao_composta(texto)):
            normalizado = _normalizar(texto).strip()
            sem_cortesia = " ".join(CORTESIA.sub("", normalizado).split())
            if normalizado in {"hmm", "talvez", ""}:
                return self._esclarecer("Posso confirmar o pedido?")
            if PERGUNTA_DO_TOTAL.search(normalizado) or CONSULTA_PEDIDO_ATUAL.search(normalizado):
                # "quanto ficou?": o resumo já tem o total, e a confirmação continua valendo
                return self._resumo_do_pedido()
            if self._fala_solta_na_confirmacao(texto):
                return "Desculpe, não entendi. Posso confirmar o pedido? Pode dizer sim ou não."
            self.etapa = "identificado"
            self._token_resumo = None
            # "nao, tira a coca": a mesma fala ja serve pra corrigir o pedido
            if not QUER_MUDAR.fullmatch(sem_cortesia):
                return self._montar_pedido(texto)
            return "Tudo bem. O que você quer mudar?"

        db = self._sessao()
        try:
            self._controle.confirmar(self._token_resumo)
            pedido = repositorio.salvar_pedido(
                db,
                self.cliente_id,
                [{"produto": i["produto"], "quantidade": i["quantidade"],
                  "observacao": i["observacao"], "preco_confirmado": i["preco"],
                  "tamanho": i.get("tamanho")}
                 for i in self.carrinho],
                endereco_entrega=self.endereco_entrega,
                forma_pagamento=self.pagamento,
            )
            numero = self.ultimo_pedido_id = pedido.id
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
        return "Pedido número {} confirmado! Obrigado, {}, e bom apetite!".format(
            numero, self._primeiro_nome())

    def _prompt_do_pedido(self, cardapio, tamanhos=()):
        if self.carrinho:
            atual = "\n".join(
                "- {} {}{}".format(
                    i["quantidade"], _com_tamanho(i["produto"], i.get("tamanho")),
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
            _tamanhos_em_texto(tamanhos),
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
            self._carregar_tamanhos(repositorio.listar_tamanhos(db))
            if (cardapio_completo(texto) or CONSULTA_HISTORICO.search(normalizado) or
                    CONSULTA_RECOMENDACAO.search(normalizado) or
                    re.search(r"\b(?:preco|precos|custa|custam|quanto)\b", normalizado)):
                return self._consultar(db, texto)
            cardapio = "\n".join([_cardapio_em_texto(repositorio.listar_cardapio(db)),
                                  _tamanhos_em_texto(repositorio.listar_tamanhos(db))])
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


def _tamanhos_em_texto(tamanhos):
    # o modelo so le o cardapio: sem isso ele dizia que a pizza tem tamanho unico ou inventava preco
    if not tamanhos:
        return ""
    linhas = []
    for grupo in sorted({t.grupo for t in tamanhos}):
        do_grupo = [t for t in tamanhos if t.grupo == grupo]
        partes = ["{} ({}{})".format(
            t.nome, "{} fatias, ".format(t.fatias) if t.fatias else "",
            "{} a menos".format(_formatar_preco(t.desconto)) if t.desconto else "preço do cardápio")
            for t in do_grupo]
        maior = next((t.nome for t in do_grupo if not t.desconto), do_grupo[-1].nome)
        linhas.append("Tamanhos de {}: {}. O preço de {} no cardápio é o do tamanho {}.".format(
            grupo, _juntar(partes), grupo, maior))
    return "\n".join(linhas)


def _cardapio_em_texto(produtos):
    return "\n".join(
        "- {} ({}): {}".format(p.nome, p.categoria, _formatar_preco(p.preco)) for p in produtos
    )
