"""Interpreta texto e a estrutura da resposta do modelo, sem banco ou serviços de IA."""

import json
import re
import unicodedata
from difflib import get_close_matches


def _normalizar(texto):
    # "Coca-Cola 2 Litros" vira "coca cola 2 litros": sem acento, minusculo e sem pontuacao,
    # pq a transcricao de voz nao devolve acento nem hifen
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^0-9a-z]+", " ", sem_acento).strip()


# o whisper as vezes escreve o cpf por extenso ("cinco dois nove..."), entao a gente
# traduz as palavras de numero tbm. "meia" eh como muita gente fala o seis
NUMEROS_FALADOS = {
    "zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3",
    "quatro": "4", "cinco": "5", "seis": "6", "meia": "6", "sete": "7", "oito": "8",
    "nove": "9",
}

DEZENAS_FALADAS = {
    "dez": "10", "onze": "11", "doze": "12", "treze": "13", "quatorze": "14", "catorze": "14", "quinze": "15",
    "dezesseis": "16", "dezessete": "17", "dezoito": "18", "dezenove": "19", "vinte": "20", "trinta": "30",
    "quarenta": "40", "cinquenta": "50", "sessenta": "60", "setenta": "70", "oitenta": "80", "noventa": "90",
}

PALAVRAS_DE_NAO = {"nao", "dispenso", "negativo", "nunca"}
PALAVRAS_DE_SIM = {
    "sim", "quero", "claro", "pode", "ok", "okay", "isso", "bora", "aceito", "gostaria",
    "desejo", "vamos", "certeza", "beleza", "manda", "certo", "correto", "exato",
    "aham", "uhum", "perfeito", "fechado", "confirmo", "confirma",
}

# o que a pessoa fala antes do dado em si: "meu nome e joao", "moro na rua x"
PREFIXO_NOME = re.compile(
    r"^\s*(?:o\s+)?(?:meu\s+nome\s+(?:completo\s+)?(?:é|e)|(?:eu\s+)?me\s+chamo|"
    r"(?:eu\s+)?sou\s+(?:o|a)?|(?:aqui\s+)?é(?:\s+(?:o|a)(?=\s))?)\s+",
    re.IGNORECASE,
)
PREFIXO_ENDERECO = re.compile(
    r"^\s*(?:o\s+)?(?:meu\s+endere[çc]o\s+(?:é|e)|(?:eu\s+)?moro\s+(?:na|no|em)|"
    r"fica\s+(?:na|no|em)|é\s+(?:na|no))\s+",
    re.IGNORECASE,
)
PARTICULAS_DO_NOME = {"da", "de", "do", "das", "dos", "e"}

# o q o llama tem q devolver a cada fala do cliente depois da identificacao.
# o ollama obriga a resposta a seguir esse schema, entao sempre vem um json q da pra ler
ESQUEMA_DO_PEDIDO = {
    "type": "object",
    "properties": {
        "resposta": {"type": "string"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "quantidade": {"type": "number"},
                    "observacao": {"type": ["string", "null"]},
                },
                "required": ["produto", "quantidade"],
            },
        },
        "endereco": {"type": ["string", "null"]},
        "fechar": {"type": "boolean"},
    },
    "required": ["resposta", "itens", "endereco", "fechar"],
}

PEDIDO_DE_TROCA = re.compile(
    r"\b(?:troca|trocar|troque|troquem|substitua|substituir|substitui)\b"
    r"|\b(?:em vez|ao inves|no lugar) d[eao]s?\b"
)
# "muda a calabresa pra mussarela". O verbo sozinho também corrige quantidade ("mude para duas"),
# então só é troca quando os dois lados do "pra" citam um produto: quem confere é o atendimento.
MUDA_PARA = re.compile(r"\b(?:mud|alter)(?:a|e|ar)\s+(.+?)\s+(?:pra|para|por|pela|pelo)\s+(.+)")
QUANTIDADES_DA_TROCA = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
}


def _item_da_troca(texto):
    texto = re.sub(r"^(?:a|o|as|os|mais)\s+", "", texto)
    partes = texto.split(maxsplit=1)
    if not partes:
        # "muda a calabresa pra pequena": tirado o tamanho, desse lado nao sobra nada
        return None, ""
    quantidade = QUANTIDADES_DA_TROCA.get(partes[0])
    if partes[0].isdigit():
        quantidade = int(partes[0])
    if quantidade is not None:
        return quantidade, partes[1] if len(partes) > 1 else ""
    return None, texto


def _nome_na_troca(texto):
    # Mesma comparação para o nome falado e o cadastrado, sem completar produtos.
    return " ".join(
        "mineral" if p == "minerais" else p.removesuffix("s")
        for p in _normalizar(texto).split() if p != "de"
    )


def extrair_digitos(texto):
    """junta todos os digitos da fala, escritos com numero ou por extenso."""
    digitos = []
    palavras = _normalizar(texto).split()
    for indice, palavra in enumerate(palavras):
        if palavra.isdigit():
            digitos.append(palavra)
        elif palavra in NUMEROS_FALADOS:
            # "vinte e um": a unidade toma o lugar do zero da dezena
            if (indice >= 2 and palavras[indice - 1] == "e" and palavras[indice - 2] in DEZENAS_FALADAS
                    and DEZENAS_FALADAS[palavras[indice - 2]].endswith("0") and digitos):
                digitos[-1] = digitos[-1][0] + NUMEROS_FALADOS[palavra]
            else:
                digitos.append(NUMEROS_FALADOS[palavra])
        elif palavra in DEZENAS_FALADAS:
            # telefone ditado em dezenas: "dezenove, nove nove..."
            digitos.append(DEZENAS_FALADAS[palavra])
    return "".join(digitos)


def sim_ou_nao(texto):
    """True, False ou None quando nao deu pra entender. o nao ganha: "nao quero" eh nao."""
    palavras = set(_normalizar(texto).split())
    if palavras & PALAVRAS_DE_NAO:
        return False
    if palavras & PALAVRAS_DE_SIM:
        return True
    return None


CONFIRMACOES_DE_UMA_PALAVRA = ("positivo", "confirmo", "confirma", "confirmado", "perfeito", "beleza", "fechado")
NAO_E_CONFIRMACAO = {"confira", "conferir", "confere"}

# Medido em fala e ruído: fala real ficou em até 0,21; ruído que virava texto, de 0,51 a 0,84.
LIMITE_SEM_FALA = 0.45


def juntar_segmentos(segmentos):
    """Descarta o que o Whisper provavelmente inventou de um ruído, para não virar pedido."""
    texto = "".join(s.text for s in segmentos if s.no_speech_prob < LIMITE_SEM_FALA)
    # O modelo às vezes repete o trecho ("pudim de leite, pudim de leite"), e isso cobraria dois.
    # Sem dígitos no trecho: número repetido em CPF ou telefone é dado, não eco.
    return re.sub(r"\b([^\W\d_][^\d]{3,}?)(?:[\s,.;]+\1\b)+", r"\1", texto, flags=re.IGNORECASE)


def confirmacao_explicita(texto):
    """Somente uma afirmação completa autoriza a gravação, nunca palavras isoladas."""
    return "?" not in texto and _normalizar(texto).strip() in {
        "sim", "confirmo", "pode confirmar", "sim pode confirmar", "sim confirmo",
        "correto", "esta correto", "isso mesmo", "pode ser", "ok", "okay",
        "sim pode", "pode", "pode sim", "sim sim", "sim por favor", "quero sim", "confirma", "confirmado",
        "isso", "e isso", "e isso ai", "certo", "ta certo", "esta certo", "tudo certo", "claro",
        "claro que sim", "com certeza", "beleza", "fechado", "perfeito", "aham", "uhum", "ta bom",
        "pode fechar", "positivo", "podia", "pois nao", "fechou", "bora", "pode mandar", "manda ver",
        "sim senhor", "sim senhora", "isso ai", "otimo", "ta otimo", "show", "confirmar", "sim confirma",
    }


# "sim, pode mandar", "isso mesmo, pode confirmar": só palavras de confirmação, com pelo menos uma forte.
# "tá" e "é" sozinhos continuam sem gravar nada: são fracas
CONFIRMACAO_FORTE = {"sim", "pode", "confirmar", "confirma", "confirmo", "confirmado", "isso", "certo", "correto",
                     "ok", "okay", "claro", "beleza", "perfeito", "positivo", "exato", "exatamente", "fechado",
                     "fechou", "certeza"}
CONFIRMACAO_FRACA = {"mesmo", "ai", "mandar", "manda", "ver", "fechar", "fecha", "ta", "esta", "tudo", "com", "por",
                     "favor", "obrigado", "obrigada", "valeu", "bom", "otimo", "pois", "e", "pode", "sim", "senhor",
                     "senhora", "o", "pedido", "isso", "agora", "ja", "entao", "show", "bora", "aham", "uhum"}


def confirmacao_composta(texto):
    palavras = set(_normalizar(texto).split())
    return ("?" not in texto and bool(palavras & CONFIRMACAO_FORTE)
            and palavras <= CONFIRMACAO_FORTE | CONFIRMACAO_FRACA)


def parece_confirmacao(texto):
    """Palavra única mal transcrita ("poisito"). Só vale na pergunta final, depois de ler o resumo."""
    palavras = _normalizar(texto).split()
    if "?" in texto or len(palavras) != 1 or palavras[0] in NAO_E_CONFIRMACAO:
        return False
    return bool(get_close_matches(palavras[0], CONFIRMACOES_DE_UMA_PALAVRA, n=1, cutoff=0.75))


def extrair_nome(texto):
    """tira o "meu nome e" da frente e a pontuacao, e capitaliza. None se nao sobrou nome."""
    nome = PREFIXO_NOME.sub("", texto or "", count=1)
    nome = re.sub(r"[^\w\s'-]|\d|_", " ", nome)
    palavras = nome.split()
    if sum(len(p) for p in palavras) < 2:
        return None
    return " ".join(
        p.lower() if i > 0 and p.lower() in PARTICULAS_DO_NOME else p.capitalize()
        for i, p in enumerate(palavras)
    )


def extrair_endereco(texto):
    endereco = PREFIXO_ENDERECO.sub("", texto or "", count=1).strip(" .,!?")
    return endereco if len(endereco) >= 5 else None


def interpretar_resposta(bruto):
    dados = json.loads(bruto)
    if (not isinstance(dados, dict) or not isinstance(dados.get("itens"), list)
            or not isinstance(dados.get("resposta"), str)
            or type(dados.get("fechar")) is not bool
            or "endereco" not in dados
            or (dados["endereco"] is not None and not isinstance(dados["endereco"], str))):
        raise ValueError("estrutura incompleta ou inválida")
    return dados
