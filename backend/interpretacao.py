"""Interpreta texto e a estrutura da resposta do modelo, sem banco ou serviços de IA."""

import json
import re
import unicodedata


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

PALAVRAS_DE_NAO = {"nao", "dispenso", "negativo", "nunca"}
PALAVRAS_DE_SIM = {
    "sim", "quero", "claro", "pode", "ok", "okay", "isso", "bora", "aceito", "gostaria",
    "desejo", "vamos", "certeza", "beleza", "manda", "certo", "correto", "exato",
}

# o que a pessoa fala antes do dado em si: "meu nome e joao", "moro na rua x"
PREFIXO_NOME = re.compile(
    r"^\s*(?:o\s+)?(?:meu\s+nome\s+(?:completo\s+)?(?:é|e)|(?:eu\s+)?me\s+chamo|"
    r"(?:eu\s+)?sou\s+(?:o|a)?|é)\s+",
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
    r"|\b(?:em vez de|no lugar de)\b"
)
QUANTIDADES_DA_TROCA = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
}


def _item_da_troca(texto):
    texto = re.sub(r"^(?:a|o|as|os|mais)\s+", "", texto)
    partes = texto.split(maxsplit=1)
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
    for palavra in _normalizar(texto).split():
        if palavra.isdigit():
            digitos.append(palavra)
        elif palavra in NUMEROS_FALADOS:
            digitos.append(NUMEROS_FALADOS[palavra])
    return "".join(digitos)


def sim_ou_nao(texto):
    """True, False ou None quando nao deu pra entender. o nao ganha: "nao quero" eh nao."""
    palavras = set(_normalizar(texto).split())
    if palavras & PALAVRAS_DE_NAO:
        return False
    if palavras & PALAVRAS_DE_SIM:
        return True
    return None


def confirmacao_explicita(texto):
    """Somente uma afirmação completa autoriza a gravação, nunca palavras isoladas."""
    return "?" not in texto and _normalizar(texto).strip() in {
        "sim", "confirmo", "pode confirmar", "sim pode confirmar", "sim confirmo",
        "correto", "esta correto", "isso mesmo", "pode ser", "ok", "okay",
    }


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
