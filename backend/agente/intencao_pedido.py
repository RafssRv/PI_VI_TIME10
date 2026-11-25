"""Evidência da fala para editar o rascunho; o JSON do modelo não é autorização.

shortcut: comandos que não cabem nesta gramática conservadora são esclarecidos,
não aproximados. Amplie com uma regressão de fala real ao aceitar outra construção.
"""

import re
from copy import deepcopy
from functools import lru_cache
from difflib import SequenceMatcher, get_close_matches

from repositorio import _normalizar, grupo_tamanho


NUMEROS = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
           "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}
NUMERO = r"\b(?:\d+|" + "|".join(NUMEROS) + r")\b"
CONSULTA = re.compile(
    r"\b(?:quanto|quanto custa|preco|precos|custa|custam|cardapio|menu|recomenda\w*|"
    r"sugere|sugest\w*|ingredientes?|contem|leva|opcoes|sabores)\b|"
    r"\b(?:quais|qual|tem|vendem|e bebidas|quero saber)\b"
)
# Pedidos antigos e sugestões saem do banco: o modelo não recebe esses dados e inventaria a resposta.
CONSULTA_HISTORICO = re.compile(
    r"\b(?:ultim[oa]s? (?:vez|pedidos?|compras?)|pedidos? anteriore?s?|pedidos? passados?|"
    r"vez passada|meu historico|historico de pedidos|meus pedidos|"
    r"o que (?:foi que )?(?:eu )?(?:ja )?pedi|ja pedi)\b"
)
CONSULTA_RECOMENDACAO = re.compile(
    r"\b(?:recomenda\w*|sugere|sugest\w*|indica|indicac\w+|de sempre|mais peco|mais pedi\w*|"
    r"mais vendid\w*|costumo pedir|minha preferida|meu preferido|minha favorita|meu favorito|"
    r"nao sei o que|nao sei qual|em duvida|(?:a|o) melhor|de bom)\b"
)
# O pedido desta chamada não é o histórico: "o que eu pedi até agora" olha o carrinho.
CONSULTA_PEDIDO_ATUAL = re.compile(
    r"\b(?:como|qual|o que)\b.*\bmeu pedido\b|\bo que (?:tem|ta|esta) no pedido\b|"
    r"\b(?:voce|vc) anotou\b|\bate agora\b|\bpedido atual\b"
)
RECLAMA_DO_PEDIDO = re.compile(r"\bnao (?:e|foi|era)\b.*\bpedi\b")
FECHAR = re.compile(r"\b(?:e so isso|so isso|pode fechar|fechar o pedido|finalizar|terminei|mais nada|nada mais)\b")
# Pagamento dito junto do item ("uma coca em dinheiro"): não é nome de produto nem observação.
PAGAMENTO_NA_FALA = re.compile(
    r"\b(?:(?:no|na|em|com|pelo|de)\s+)?(?:pix|pics|picks|piques|pixe|dinheiro|maquininha|"
    r"cartao(?:\s+de\s+(?:credito|debito))?|credito|debito)\b"
)
# "Não é só isso" pede mais; "não, é só isso" encerra. Só a vírgula separa, por isso olha o texto cru.
AINDA_NAO_ACABOU = re.compile(r"\bn[aã]o\s+(?:[eé]\s+)?s[oó]\b", re.IGNORECASE)
# Sem produto na frase, basta conter isto: "não, não quero mais nada", "quero pagar no pix".
FIM_DO_PEDIDO = re.compile(r"\b(?:mais nada|nada mais|so isso|quero pagar|pode cobrar|"
                           r"fecha(?:r)? a conta|quero fechar|quero encerrar)\b")
# Como as pessoas mandam pôr e tirar um item. "põe" chega aqui sem acento.
VERBOS_DE_ADICIONAR = (r"adicione|adicionar|adiciona|acrescente|acrescentar|acrescenta|inclua|incluir|inclui|"
                       r"coloque|colocar|coloca|bote|botar|bota|ponha|poe|anote|anotar|anota")
VERBOS_DE_REMOVER = (r"tire|tira|tirar|retire|retira|retirar|remova|remover|remove|exclua|excluir|exclui|"
                     r"cancele|cancelar|cancela|esquece|esqueca|esquecer")
# "pode ser sem cebola", "com bastante orégano, por favor": observação dita sem o produto
# "a pizza", "o refri": o tipo do item no lugar do nome, e a parte da categoria que identifica o tipo.
# "a pizza de calabresa" já é nome do cardápio, então o "de" logo depois impede a troca.
TIPOS_DE_ITEM = {"pizza": "pizza", "bebida": "bebida", "refri": "bebida", "refrigerante": "bebida",
                 "sobremesa": "sobremesa"}
APELIDO_DO_ITEM = re.compile(r"\b(a|o|as|os|da|do|das|dos|na|no|nas|nos)\s+(pizzas?|bebidas?|refris?|refrigerantes?|"
                             r"sobremesas?)\b(?!\s+(?:de|da|do)\b)", re.IGNORECASE)
OBSERVACAO_SOLTA = re.compile(r"(?:(?:sim|mas|n[aã]o|na verdade|pode ser|quero|queria|e|ah|ent[aã]o)[\s,]+)*"
                              r"((?:sem|com)\s+.+?)(?:,?\s*por favor)?",
                              re.IGNORECASE)
# "tira a cebola", "não coloca cebola na calabresa": o ingrediente, e o produto se for dito
TIRA_INGREDIENTE = re.compile(r"(?:tira|tire|retira|retire|n[aã]o\s+(?:coloca|coloque|bota|bote|p[oõ]e|ponha))\s+"
                              r"(?:(?:a|o|as|os)\s+)?(.+?)(?:\s+(?:da|do|na|no)\s+(.+?))?(?:,?\s*por favor)?",
                              re.IGNORECASE)
# "meia calabresa meia mussarela", "metade frango metade calabresa", "meio a meio"
MEIO_A_MEIO = re.compile(r"\bmeio a meio\b|\b(?:meia|metade)\b.+\b(?:meia|metade)\b")
# "duas pizzas grandes, uma de calabresa e uma de frango", "duas grandes, calabresa e mussarela"
SABORES_DIVIDIDOS = re.compile(
    r"(?P<inicio>.*?)\b(?P<n>duas|dois|tr[eê]s|quatro|[234])\s+(?P<pizzas>pizzas\b[\s,:]*)?"
    r"(?P<tamanho>(?:tamanho\s+)?(?:pequenas?|m[eé]dias?|grandes?|brotos?))?\s*[,:]?\s*(?P<sabores>.+)",
    re.IGNORECASE)
# "mais uma", "manda outra", "mais duas iguais", "duas a mais": sem produto, repete o último item
MAIS_DO_MESMO = re.compile(
    r"(?:(?:coloca|coloque|manda|mande|bota|bote|poe|ponha|quero|queria|me ve|traz|traga|e|pode ser)\s+)*"
    r"(?:mais\s+(" + NUMERO + r")|(" + NUMERO + r")\s+a\s+mais|outr[ao]s?(?:\s+(" + NUMERO + r"))?)"
    r"(?:\s+(?:igual|iguais|dessa|desse|dessas|desses|da mesma|do mesmo|por favor))*")
# "pode colocar cebola": só desfaz um "sem cebola" já anotado
COLOCA_INGREDIENTE = re.compile(r"(?:pode\s+)?(?:coloca|coloque|colocar|bota|bote|botar|p[oõ]e|ponha|p[oô]r)\s+"
                                r"(?:(?:a|o|as|os)\s+)?(.+?)(?:\s+(?:da|do|na|no)\s+(.+?))?(?:,?\s*por favor)?",
                                re.IGNORECASE)
NAO_COLOCA = re.compile(r"nao\s+(?:" + VERBOS_DE_ADICIONAR + r"|manda|mande)\s+(.+?)(?:\s+nao)?")
REMOVER = re.compile(r"\b(?:" + VERBOS_DE_REMOVER + r"|nao quero)\b")
# Tamanho dito na fala: de pizza ("grande") ou de refrigerante ("lata", "de 600", "2 litros").
# "Em média" não é tamanho, e o endereço ("Rua Grande") nem é olhado.
# Vocabulário base, igual ao seed. Tamanho novo cadastrado no banco entra pela classe Tamanhos.
PALAVRAS_DE_TAMANHO = r"pequen[ao]s?|brotos?|m[eé]di[ao]s?|grandes?|gigantes?|fam[ií]lia"
VOLUMES_DE_TAMANHO = r"latas?|latinhas?|(?:600|seiscentos)(?:\s*ml|\s+mililitros)?|(?:2|dois)\s+litros?"
# Cada tamanho só vale para os produtos do grupo dele: pizza não vem em lata.
GRUPO_DO_TAMANHO = {"pequena": "pizza", "média": "pizza", "grande": "pizza",
                    "Lata": "refrigerante", "600 ml": "refrigerante", "2 Litros": "refrigerante"}
ENDERECO_NA_FALA = re.compile(r"\b(?:rua|avenida|av|travessa|alameda|estrada|rodovia)\b", re.IGNORECASE)
# Gigante e família não existem no cardápio: o atendente avisa e pergunta de novo.
TAMANHO_INDISPONIVEL = "indisponivel"
# "muda pra média", "pode ser média": um verbo de mudança e só palavras de ligação em volta do tamanho
MUDA_O_TAMANHO = {"muda", "mude", "mudar", "troca", "troque", "trocar", "altera", "altere", "alterar",
                  "deixa", "deixe", "pode", "fica", "quero", "queria", "prefiro", "melhor"}
LIGA_O_TAMANHO = {"ser", "na", "verdade", "entao", "ah", "o", "a", "tamanho", "pra", "para", "por", "sim",
                  "eu", "me", "faz", "faca", "favor", "ela", "ele", "isso"}
PEDE_MAIS_UM = re.compile(r"\b(?:mais|outra|outro|outras|outros|quero|queria|" + VERBOS_DE_ADICIONAR + r")\b")
CORRIGIR = re.compile(r"\b(?:na verdade|so|apenas|corrija|corrigir|altere|alterar|altera|deixe|deixa|mude|muda)\b")
# "muda a coca pra duas", "mude para duas": a quantidade nova vem depois do "pra"
MUDA_A_QUANTIDADE = re.compile(r"(.*?\b(?:mude|muda|altere|altera|deixe|deixa))\s+(?:(?:a|o|as|os)\s+)?(.*?)\s*"
                               r"\b(?:pra|para)\s+(" + NUMERO + r")")


# Parecem nomes do cardápio, mas são palavras do dia a dia: "quanto" não é "quatro queijos".
# Os verbos também: a comparação aproximada levava "cancela" para "canela" e "anota" para "fanta".
NAO_E_PRODUTO = {"quanto", "quanta", *VERBOS_DE_ADICIONAR.split("|"), *VERBOS_DE_REMOVER.split("|")}
# Grafias que ficam longe demais do nome para a comparação aproximada.
GRAFIAS = {"calabreza": "calabresa", "mozarela": "mussarela", "muzarela": "mussarela",
           "muzzarela": "mussarela", "mozzarela": "mussarela", "mozzarella": "mussarela",
           # "moçarela" e "muçarela" sao as grafias do dicionario, e o whisper escreve assim
           "mocarela": "mussarela", "mucarela": "mussarela", "mozarella": "mussarela"}
# Fala inteira que encerra o pedido. A cortesia ("obrigado") é retirada antes de comparar.
FALAS_DE_FECHAR = {
    "e so isso", "so isso", "so isso mesmo", "e so isso mesmo", "e isso", "e isso ai", "e isso mesmo",
    "e so", "so", "era isso", "era so isso", "por enquanto e so", "por enquanto e isso",
    "pode fechar", "fechar", "fecha", "fecha o pedido", "fechar o pedido", "pode fechar o pedido",
    "finalizar", "finaliza", "pode finalizar", "quero finalizar", "finaliza o pedido", "terminei",
    "acabei", "acabou", "mais nada", "nada mais", "nao quero mais nada", "ta bom assim", "esta bom assim",
    "quero pagar", "vou pagar", "pagar", "pode cobrar", "encerrar", "pode encerrar",
    # ainda montando o pedido, "pode confirmar" so pede o resumo: gravar exige outro sim depois dele
    "pode confirmar", "sim pode confirmar", "pode confirmar o pedido", "confirma o pedido",
}
# "finalize o pedido", "feche", "pode encerrar a conta": a ordem de fechar dita de varios jeitos
ORDEM_DE_FECHAR = re.compile(r"(?:pode |quero |vamos )?(?:finaliz|fech|encerr)(?:a|e|ar)"
                             r"(?: (?:o|meu) pedido| a conta)?")


def parece_so_isso_mesmo(fala):
    """
    o microfone ruim faz o whisper ouvir "so isso mesmo" como "sais mesmo", "saiso mesmo" ou
    "sai-se mesmo". frase curta que comeca com s, termina em "mesmo" e soa parecido conta como fechar
    """
    palavras = fala.split()
    if not 2 <= len(palavras) <= 4 or palavras[-1] != "mesmo" or not palavras[0].startswith("s"):
        return False
    # o "so i" quase sempre vira "sai" no whisper
    return palavras[0].startswith("sai") or SequenceMatcher(None, "soissomesmo", "".join(palavras)).ratio() >= 0.78


def eh_fala_de_fechar(fala, texto_cru=""):
    # "nao, feche o pedido": com a virgula, o "nao" responde o "quer algo mais?" e o resto fecha
    if re.match(r"\s*n[aã]o\s*[,.!]", texto_cru, re.IGNORECASE):
        fala = fala.removeprefix("nao ")
    return fala in FALAS_DE_FECHAR or bool(ORDEM_DE_FECHAR.fullmatch(fala)) or parece_so_isso_mesmo(fala)


def quantidade(texto):
    encontrados = re.findall(NUMERO, texto)
    if not encontrados:
        return None
    valor = encontrados[-1]
    return int(valor) if valor.isdigit() else NUMEROS[valor]


def radical(palavra):
    palavra = "mineral" if palavra == "minerais" else palavra.removesuffix("s")
    # Grafia observada no Whisper real; se ambos os nomes existirem, fica ambíguo.
    return GRAFIAS.get(palavra, palavra)


def comando_negado(texto):
    return bool(re.search(
        r"\bn[aã]o\s+(?:(?:quero|pode|vamos|precisa|deve)\s+)?"
        r"(?:tirar|tire|tira|retire|retirar|remover|remova|excluir|troque|trocar|"
        r"adicionar|adicione|acrescente|fechar|finalizar)\b", texto, re.IGNORECASE))


def acao_do_trecho(texto, anterior="adicionar"):
    if REMOVER.search(texto):
        return "remover"
    if CORRIGIR.search(texto):
        return "corrigir"
    if re.search(r"\b(?:quero|queria|mais|" + VERBOS_DE_ADICIONAR + r")\b", texto):
        return "adicionar"
    return anterior


def _numero_do_nome(texto):
    # O Whisper escreve "Pizza 4 Queijos": esse 4 faz parte do nome, não é a quantidade.
    texto = re.sub(r"\b4\s+queijos?\b", "quatro queijos", texto, flags=re.IGNORECASE)
    # "pizza de quatro queijos": no cardápio é "Pizza Quatro Queijos", e o "quatro" depois do "de" virava quantidade
    return re.sub(r"\b(pizzas?)\s+de\s+(quatro\s+queijos?)\b", r"\1 \2", texto, flags=re.IGNORECASE)


def tamanho_canonico(palavra):
    palavra = _normalizar(palavra)
    if palavra.startswith(("pequen", "broto")):
        return "pequena"
    if palavra.startswith("medi"):
        return "média"
    if palavra.startswith("grande"):
        return "grande"
    if palavra.startswith(("lata", "latinha")):
        return "Lata"
    if palavra.startswith(("600", "seiscentos")):
        return "600 ml"
    if palavra.startswith(("2 litro", "dois litro")):
        return "2 Litros"
    return TAMANHO_INDISPONIVEL


def _forma_falada(nome):
    """
    Regex de como se fala um tamanho do banco: sem depender de acento, com plural e, em palavra
    única, com o gênero ("gigante", "gigantes"; "extra grande"; "350 ml"; "1 litro", "um litro").
    shortcut: número acima de dez só é reconhecido em dígitos, amplie quando o Whisper escrever por extenso.
    """
    letras = {"a": "[aáàâã]", "e": "[eéê]", "i": "[ií]", "o": "[oóôõ]", "u": "[uúü]", "c": "[cç]"}
    por_extenso = {str(valor): palavra for palavra, valor in NUMEROS.items() if palavra not in ("uma", "duas")}
    palavras = _normalizar(nome).split()
    partes = []
    for indice, palavra in enumerate(palavras):
        if palavra.isdigit():
            partes.append("(?:{}|{})".format(palavra, por_extenso[palavra]) if palavra in por_extenso else palavra)
            continue
        ultima = indice == len(palavras) - 1
        if len(palavras) == 1 and palavra[-1] in "ao":
            partes.append("".join(letras.get(c, re.escape(c)) for c in palavra[:-1]) + "[ao]s?")
        else:
            corpo = palavra.removesuffix("s") if ultima else palavra
            partes.append("".join(letras.get(c, re.escape(c)) for c in corpo) + ("s?" if ultima else ""))
    forma = partes[0]
    for anterior, parte in zip(palavras, partes[1:]):
        # "350ml" e "350 ml" são a mesma coisa; entre palavras o espaço é obrigatório
        forma += (r"\s*" if anterior.isdigit() else r"\s+") + parte
    return forma


class Tamanhos:
    """
    Como os tamanhos são falados e a que grupo pertencem. Sem argumento vale o vocabulário base;
    com os pares (grupo, nome) da tabela tamanho, o que foi cadastrado a mais também é reconhecido.
    """

    def __init__(self, do_banco=()):
        self.grupos = {nome: {grupo} for nome, grupo in GRUPO_DO_TAMANHO.items()}
        self._novos = []
        palavras, volumes = [], []
        for grupo, nome in do_banco:
            if _normalizar(tamanho_canonico(nome)) != _normalizar(nome) and not any(n == nome for _, n in self._novos):
                forma = _forma_falada(nome)
                self._novos.append((re.compile(forma, re.IGNORECASE), nome))
                (volumes if _normalizar(nome)[:1].isdigit() else palavras).append(forma)
            self.grupos.setdefault(self.canonico(nome), set()).add(grupo)
        # os novos vêm antes: "extra grande" não pode parar em "grande"
        self.falado = re.compile(
            r"(?<!em )\b(?:(?:(?:de|do|no|na)\s+)?tamanho\s+)?(" + "|".join(palavras + [PALAVRAS_DE_TAMANHO]) + r")\b"
            r"|\b(?:(?:de|da|na|em)\s+)?(" + "|".join(volumes + [VOLUMES_DE_TAMANHO]) + r")\b",
            re.IGNORECASE)

    def canonico(self, palavra):
        for forma, nome in self._novos:
            if forma.fullmatch(palavra.strip()):
                return nome
        return tamanho_canonico(palavra)

    def do_grupo(self, tamanho, grupo):
        return grupo in self.grupos.get(tamanho, ())

    def serve_para(self, tamanho, produto):
        """Tamanho "família" serve pra avisar qualquer produto com tamanho; o resto só o do grupo."""
        grupo = grupo_tamanho(produto)
        return bool(grupo) and (tamanho == TAMANHO_INDISPONIVEL or self.do_grupo(tamanho, grupo))


@lru_cache(maxsize=8)
def _tamanhos_de(chave):
    return Tamanhos(chave)


def tamanhos_do_banco(linhas):
    """Vocabulário para as linhas da tabela tamanho; o mesmo cadastro reaproveita o mesmo objeto."""
    return _tamanhos_de(tuple(sorted((t.grupo, t.nome) for t in linhas)))


TAMANHOS_BASE = Tamanhos()


def separar_tamanhos(texto, vocabulario=TAMANHOS_BASE):
    """
    Tira o tamanho da fala para os nomes do cardápio continuarem inteiros ("pizza grande de
    calabresa" vira "pizza de calabresa"). Devolve o texto limpo e [(posição, tamanho)], onde
    posição é o índice da palavra seguinte no texto limpo, já normalizado.
    """
    texto = texto or ""
    endereco = ENDERECO_NA_FALA.search(texto)
    corte = endereco.start() if endereco else len(texto)
    partes, achados, ultimo = [], [], 0
    for achado in vocabulario.falado.finditer(texto, 0, corte):
        partes.append(texto[ultimo:achado.start()])
        posicao = len(_normalizar(_numero_do_nome("".join(partes))).split())
        achados.append((posicao, vocabulario.canonico(achado.group(1) or achado.group(2))))
        ultimo = achado.end()
    if not achados:
        return texto, []
    partes.append(texto[ultimo:])
    limpo = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s+", " ", "".join(partes))).strip()
    return limpo, achados


def _donos_dos_tamanhos(tamanhos, achados, palavras, vocabulario):
    """
    Cada tamanho vale para a pizza onde foi dito: colado no nome ("calabresa grande"), no meio
    dele ("pizza grande de calabresa"), logo antes ("uma grande de calabresa") ou depois de um
    verbo de ligação ("a calabresa é média"). Tamanho colado em outro produto ("coca grande") ou
    sem produto nenhum ("grande") fica solto.
    """
    ligacao = {"e", "eh", "fica", "ficam", "seja", "sejam", "sera", "sao", "vai", "ser", "pode", "a", "o", "as", "os",
               "ela", "elas", "essa", "esse", "pizza", "pizzas"}
    donos, soltos, errados = {}, [], {}
    for posicao, tamanho in tamanhos:
        dono = None
        colado = next((i for i, (inicio, fim, _) in enumerate(achados) if inicio <= posicao <= fim), None)
        if colado is None:
            dono = next((i for i, (inicio, _, _) in enumerate(achados) if inicio >= posicao), None)
            anteriores = [i for i, (_, fim, _) in enumerate(achados) if fim <= posicao]
            if dono is None and anteriores and set(palavras[achados[anteriores[-1]][1]:posicao]) <= ligacao:
                dono = anteriores[-1]
        else:
            dono = colado
        if dono is not None:
            candidatos = achados[dono][2]
            no_nome = f" {_normalizar(tamanho).replace('litros', 'litro')} " in f" {_normalizar(candidatos[0].nome).replace('litros', 'litro')} "
            if (len(candidatos) == 1 and not vocabulario.serve_para(tamanho, candidatos[0]) and not no_nome
                    and vocabulario.do_grupo(tamanho, "refrigerante")):
                # "agua de 2 litros", "suco 600": esse volume nao existe no cardapio pra esse produto
                errados[dono] = tamanho
            if len(candidatos) != 1 or not vocabulario.serve_para(tamanho, candidatos[0]):
                dono = None
        if dono is None:
            soltos.append((posicao, tamanho))
        else:
            donos.setdefault(dono, []).append(tamanho)
    return donos, soltos, errados


def _divisoes_por_tamanho(achados, palavras, soltos):
    """
    "duas calabresas, uma grande e uma média": cada número depois do produto leva o tamanho dito logo em
    seguida. Devolve ({índice do achado: [(quantidade, tamanho)]}, posições de tamanho usadas), só quando
    a cauda inteira é isso; um número solto no fim é a quantidade do próximo item ("e uma coca").
    """
    tamanho_em = dict(soltos)
    divisoes, usadas = {}, set()
    for indice, (_, fim, _) in enumerate(achados):
        seguinte = achados[indice + 1][0] if indice + 1 < len(achados) else len(palavras)
        pares = []
        for posicao in range(fim, seguinte):
            palavra = palavras[posicao]
            if palavra == "e":
                continue
            if re.fullmatch(NUMERO, palavra) and posicao + 1 in tamanho_em:
                pares.append((quantidade(palavra), tamanho_em[posicao + 1], posicao + 1))
                continue
            proximo = indice + 1 < len(achados)
            if not (proximo and all(p == "e" or re.fullmatch(NUMERO, p) for p in palavras[posicao:seguinte])):
                pares = []
            break
        if len(pares) > 1:
            divisoes[indice] = [(q, t) for q, t, _ in pares]
            usadas.update(p for _, _, p in pares)
    return divisoes, usadas


def _juntar_iguais(itens):
    """Duas linhas do mesmo produto, tamanho e observação viram uma, somando as quantidades."""
    juntos = []
    for item in itens:
        igual = next((i for i in juntos if i["produto"] == item["produto"]
                      and i.get("observacao") == item.get("observacao")
                      and i.get("tamanho") == item.get("tamanho")), None)
        if igual:
            igual["quantidade"] += item["quantidade"]
        else:
            juntos.append(item)
    itens[:] = juntos


def _responder_tamanho(novo, pendente, soltos, palavras, texto, produtos, vocabulario):
    """
    Resposta a "qual o tamanho?". Devolve (dúvida que continua, evidências). Com dois tamanhos
    para a mesma linha ("uma grande e uma média"), só separa quando as quantidades fecham.
    """
    alvos = [i for i in novo if i["produto"] == pendente.get("produto") and not i.get("tamanho")]
    if not alvos:
        return None, []
    produto = next((p for p in produtos if p.nome == pendente.get("produto")), None)
    distintos = list(dict.fromkeys(t for _, t in soltos))
    # "grande" para a coca não é tamanho de refrigerante: avisa e pergunta de novo
    if TAMANHO_INDISPONIVEL in distintos or (produto and not all(vocabulario.serve_para(t, produto) for t in distintos)):
        return {"campo": "tamanho", "produto": pendente["produto"], "indisponivel": True}, []
    if len(distintos) == 1:
        for alvo in alvos:
            alvo["tamanho"] = distintos[0]
        _juntar_iguais(novo)
        return None, [{"acao": "tamanho", "produto": pendente["produto"], "tamanho": distintos[0],
                       "quantidade": sum(a["quantidade"] for a in alvos), "observacao": alvos[0]["observacao"],
                       "trecho": texto}]
    pares = []
    for posicao, tamanho in soltos:
        anterior = palavras[posicao - 1] if posicao > 0 else ""
        pares.append((quantidade(anterior) if re.fullmatch(NUMERO, anterior) else None, tamanho))
    if (len(alvos) == 1 and all(q for q, _ in pares) and len(distintos) == len(pares)
            and sum(q for q, _ in pares) == alvos[0]["quantidade"]):
        base = alvos[0]
        posicao = novo.index(base)
        novo[posicao:posicao + 1] = [{**base, "quantidade": q, "tamanho": t} for q, t in pares]
        _juntar_iguais(novo)
        return None, [{"acao": "tamanho", "produto": base["produto"], "tamanho": t, "quantidade": q,
                       "observacao": base["observacao"], "trecho": texto} for q, t in pares]
    return {"campo": "tamanho", "produto": pendente["produto"], "misto": True}, []


def mencoes(texto, produtos):
    """Maior trecho contíguo do nome; nunca resolve um nome com vários candidatos."""
    palavras = _normalizar(_numero_do_nome(texto)).split()
    radicais = [radical(p) for p in palavras]
    nomes = [(p, [radical(t) for t in _normalizar(p.nome).split()]) for p in produtos]
    ignorar = {"de", "do", "da", "com", "sem", "e", "o", "a", "litro", "ml"}
    # O Whisper erra letras de nomes ("calabresia", "margarita"). Só corrige quando há um único
    # parecido no cardápio, e o resumo ainda é lido para o cliente confirmar.
    vocabulario = {t for _, nome in nomes for t in nome if len(t) >= 5}
    for i, palavra in enumerate(radicais):
        if len(palavra) >= 5 and palavra not in vocabulario and palavra not in NAO_E_PRODUTO:
            parecidas = get_close_matches(palavra, vocabulario, n=2, cutoff=0.8)
            if len(parecidas) == 1:
                palavras[i] = radicais[i] = parecidas[0]
    resultado = []
    inicio = 0
    while inicio < len(palavras):
        if radicais[inicio] in ignorar or palavras[inicio].isdigit():
            inicio += 1
            continue
        encontrado = None
        for fim in range(len(palavras), inicio, -1):
            trecho = radicais[inicio:fim]
            candidatos = [p for p, nome in nomes
                          if any(nome[i:i + len(trecho)] == trecho for i in range(len(nome)))]
            if candidatos:
                encontrado = (inicio, fim, candidatos)
                break
        if encontrado:
            resultado.append(encontrado)
            inicio = encontrado[1]
        else:
            inicio += 1
    return palavras, resultado


def eh_consulta(texto):
    normal = _normalizar(texto)
    comando = re.match(r"(?:pode|poderia) (?:adicionar|acrescentar|colocar|incluir|botar|anotar|"
                       r"retirar|tirar|remover|excluir|trocar|substituir)\b", normal)
    return bool(CONSULTA.search(normal) or CONSULTA_HISTORICO.search(normal) or
                CONSULTA_RECOMENDACAO.search(normal) or CONSULTA_PEDIDO_ATUAL.search(normal) or
                RECLAMA_DO_PEDIDO.search(normal) or normal.startswith("se ") or
                ("?" in texto and not comando))


def cardapio_completo(texto):
    normal = _normalizar(texto)
    return bool(re.search(r"\b(?:cardapio|menu)\b", normal) or
                re.search(r"\b(?:todos|todas)\b.*\b(?:produtos|opcoes|precos)\b", normal))


def _apelido_do_item(texto, produtos, atual):
    """
    "a pizza", "o refri": com um só item daquele tipo no pedido, o apelido vira o nome dele.
    Devolve (texto, nomes do apelido que aponta mais de um item, ou None).
    """
    categoria = {p.nome: _normalizar(p.categoria or "") for p in produtos}
    ambiguos = []

    def trocar(achado):
        tipo = TIPOS_DE_ITEM[_normalizar(achado[2]).removesuffix("s")]
        nomes = list(dict.fromkeys(i["produto"] for i in atual if tipo in categoria.get(i["produto"], "")))
        if len(nomes) > 1:
            ambiguos.append(nomes)
        return "{} {}".format(achado[1], nomes[0]) if len(nomes) == 1 else achado[0]

    return APELIDO_DO_ITEM.sub(trocar, texto), (ambiguos[0] if ambiguos else None)


def _resposta_de_qual_item(texto, produtos, atual, pendente):
    """"a calabresa" responde "qual delas?": vale a fala guardada, aplicada nesse item. Outra fala segue normal."""
    opcoes = [p for p in produtos if p.nome in pendente["itens"]]
    palavras, achados = mencoes(texto, opcoes)
    nomes = {p.nome for _, _, ps in achados for p in ps}
    fora = [p for i, p in enumerate(palavras) if not any(a <= i < b for a, b, _ in achados)]
    if len(nomes) != 1 or not set(fora) <= {"a", "o", "as", "os", "de", "da", "do", "essa", "esse", "pizza", "e"}:
        return texto
    nome = nomes.pop()
    fala = _apelido_do_item(pendente["fala"], produtos, [i for i in atual if i["produto"] == nome])[0]
    # "mais uma" não tem apelido pra trocar: o nome escolhido vai no fim ("mais uma Coca-Cola")
    return fala if fala != pendente["fala"] else "{} {}".format(fala, nome)


def _observacao_solta(texto, produtos, atual):
    """
    "sem cebola", "tira a cebola", "não coloca cebola na calabresa", "pode colocar cebola": a observação
    sem o produto (ou com ele no fim) vale para o item do pedido.
    Devolve (texto, dúvida, edição): a edição é (posição do item no pedido, observação nova) e muda o
    item direto. Com mais de um item no pedido e nenhum citado, pergunta qual.
    """
    limpo = texto.strip(" .,!?")
    solta = OBSERVACAO_SOLTA.fullmatch(limpo)
    tira = TIRA_INGREDIENTE.fullmatch(limpo)
    coloca = COLOCA_INGREDIENTE.fullmatch(limpo)
    if solta:
        observacao, dono = solta[1], None
    elif tira:
        observacao, dono = "sem " + tira[1], tira[2]
    elif coloca:
        observacao, dono = "com " + coloca[1], coloca[2]
    else:
        return texto, None, None
    if (mencoes(observacao, produtos)[1] or (dono and not mencoes(dono, produtos)[1])
            or set(_normalizar(observacao).split()) & set(TIPOS_DE_ITEM)):
        return texto, None, None  # "sem a coca", "tira a coca" e "da casa" não são observação de item
    if dono:
        nomes = {p.nome for _, _, ps in mencoes(dono, produtos)[1] for p in ps}
        alvos = [i for i in atual if i["produto"] in nomes]
        if len(nomes) == 1 and not alvos:
            return texto, {"campo": "fora_do_pedido", "produto": nomes.pop()}, None
    elif len(atual) != 1:
        if coloca:
            return texto, None, None
        return texto, {"campo": "qual_observacao", "observacao": observacao,
                       "itens": [i["produto"] for i in atual]}, None
    else:
        alvos = atual
    if len(alvos) != 1:
        # duas linhas do mesmo produto: o caminho de correção pergunta qual
        return "{} {}".format(dono, observacao), None, None
    nova = _juntar_observacao(alvos[0]["observacao"], observacao)
    if coloca and observacao in (nova or ""):
        return texto, None, None  # "coloca X" só desfaz um "sem X"; senão segue o caminho normal
    return texto, None, (atual.index(alvos[0]), nova)


def _sabores_divididos(texto, produtos):
    """
    "duas pizzas grandes, uma de calabresa e uma de frango": a quantidade e o tamanho vêm antes e valem
    pra cada sabor. Vira "uma Pizza de Calabresa grande e uma Pizza de Frango com Catupiry grande", só
    quando o número de sabores bate com a quantidade.
    """
    dividido = SABORES_DIVIDIDOS.fullmatch(texto.strip())
    if not dividido or not (dividido["pizzas"] or dividido["tamanho"]):
        return texto
    palavras, achados = mencoes(dividido["sabores"], produtos)
    # "duas pizzas grandes, calabresa e uma coca": a coca não é sabor, então não divide
    if (len(achados) != quantidade(_normalizar(dividido["n"]))
            or any(len(c) != 1 or grupo_tamanho(c[0]) != "pizza" for _, _, c in achados)):
        return texto
    entre = [p for i, p in enumerate(palavras[:achados[-1][1]]) if not any(a <= i < b for a, b, _ in achados)]
    if not set(entre) <= {"uma", "um", "de", "da", "do", "e", "a", "o", "sabor", "sabores"}:
        return texto
    tamanho = re.sub(r"^tamanho\s+|s$", "", (dividido["tamanho"] or "").lower())
    itens = " e ".join("uma {} {}".format(c[0].nome, tamanho).strip() for _, _, c in achados)
    resto = " ".join(palavras[achados[-1][1]:])
    return " ".join(p for p in (dividido["inicio"], itens, resto) if p)


def _mais_do_mesmo(texto, produtos, atual, referencia):
    """
    "mais uma", "manda outra", "mais duas iguais": repete o último item citado, com o mesmo tamanho e a
    mesma observação. Devolve (rascunho, dúvida, evidências), ou None quando a fala não é isso.
    """
    pedido = MAIS_DO_MESMO.fullmatch(_normalizar(texto).strip(" .,!?"))
    if not pedido or mencoes(texto, produtos)[1]:
        return None
    numero = next((g for g in pedido.groups() if g), None)
    qtd = quantidade(numero) if numero else 1
    citados = [i for i in atual if i["produto"] == referencia]
    alvos = citados if len(citados) == 1 else atual
    if len(alvos) != 1:
        # a resposta "a coca" vira "mais uma Coca-Cola"; pedido vazio só avisa
        return deepcopy(atual), {"campo": "qual_item", "fala": texto,
                                 "itens": list(dict.fromkeys(i["produto"] for i in atual))}, []
    novo = deepcopy(atual)
    alvo = novo[atual.index(alvos[0])]
    alvo["quantidade"] += qtd
    return novo, None, [{"acao": "adicionar", "produto": alvo["produto"], "quantidade": qtd,
                         "tamanho": alvo.get("tamanho"), "observacao": alvo["observacao"], "trecho": texto}]


def _juntar_observacao(anterior, nova):
    """
    "com bastante orégano" soma ao "sem cebola"; "com cebola" desfaz o "sem cebola"; "sem cebola" troca o
    "com cebola". Devolve a observação inteira, ou None quando não sobra nada.
    """
    ingredientes = lambda obs: set(_normalizar(obs).split()) - {"sem", "com"}
    partes = [p for p in re.split(r"\s*(?:,|\be\b)\s*", anterior or "") if p]
    mesmos = [p for p in partes if ingredientes(p) & ingredientes(nova)]
    final = [p for p in partes if p not in mesmos]
    desfaz = _normalizar(nova).startswith("com") and any(_normalizar(p).startswith("sem") for p in mesmos)
    if not desfaz:
        final.append(nova)
    return " e ".join(final) or None


def interpretar(texto, produtos, atual, pendente=None, referencia=None, vocabulario=TAMANHOS_BASE):
    """Retorna (rascunho, pendência de campo, evidências) sem efeitos externos."""
    texto = _sabores_divididos(_numero_do_nome(texto), produtos)
    if pendente and pendente.get("campo") == "qual_item":
        texto = _resposta_de_qual_item(texto, produtos, atual, pendente)
        pendente = None
    if pendente and pendente.get("campo") == "qual_observacao":
        # "sem cebola" -> "qual item?" -> "a calabresa": a resposta leva a observação que ficou esperando
        if mencoes(texto, produtos)[1] and not re.search(r"\b(?:sem|com)\b", _normalizar(texto)):
            texto = texto.strip(" .,!?") + " " + pendente["observacao"]
        pendente = None
    texto, qual = _apelido_do_item(texto, produtos, atual)
    if qual:
        # "a pizza sem cebola" com duas pizzas: pergunta qual, e a resposta aplica esta mesma fala nela
        return deepcopy(atual), {"campo": "qual_item", "fala": texto, "itens": qual}, []
    muda = MUDA_A_QUANTIDADE.fullmatch(_normalizar(texto).strip(" .,!?"))
    if muda:
        # "altere a coca para duas" vira "altere duas coca", que o caminho de correção já entende
        verbo, citado, numero = muda.groups()
        if not citado:
            if len(atual) != 1:
                return deepcopy(atual), {"campo": "qual_muda", "para": numero, "quantidade": True,
                                         "itens": [i["produto"] for i in atual]}, []
            citado = atual[0]["produto"]
        nomes = {p.nome for _, _, ps in mencoes(citado, produtos)[1] for p in ps}
        if len(nomes) == 1 and not any(i["produto"] in nomes for i in atual):
            # mudar a quantidade do que não foi pedido não é pedir de novo
            return deepcopy(atual), {"campo": "fora_do_pedido", "produto": nomes.pop()}, []
        # "muda a coca pra zero" é tirar a coca
        texto = "tira " + citado if numero == "zero" else "{} {} {}".format(verbo, numero, citado)
    negado = NAO_COLOCA.fullmatch(_normalizar(texto).strip(" .,!?"))
    if negado:
        palavras, achados = mencoes(negado[1], produtos)
        fora = [p for i, p in enumerate(palavras) if not any(a <= i < b for a, b, _ in achados)]
        if achados and set(fora) <= {"a", "o", "as", "os", "uma", "um"}:
            # "não coloca coca não": só o produto depois do verbo negado, então é tirar ele
            texto = "tira " + negado[1]
    repetido = _mais_do_mesmo(texto, produtos, atual, referencia)
    if repetido:
        return repetido
    texto, duvida, edicao = _observacao_solta(texto, produtos, atual)
    if duvida:
        return deepcopy(atual), duvida, []
    if edicao:
        novo = deepcopy(atual)
        alvo = novo[edicao[0]]
        alvo["observacao"] = edicao[1]
        evidencia = {"acao": "corrigir", "produto": alvo["produto"], "quantidade": alvo["quantidade"],
                     "tamanho": alvo.get("tamanho"), "observacao": edicao[1], "trecho": texto}
        _juntar_iguais(novo)
        return novo, None, [evidencia]
    texto, tamanhos = separar_tamanhos(texto, vocabulario)
    normal = _normalizar(texto)
    # "Não temos X" é aviso, não pergunta aberta: não pode prender as falas seguintes.
    if pendente and (pendente.get("nao_encontrado") or pendente.get("campo") == "fora_do_pedido"):
        pendente = None
    novo = deepcopy(atual)
    evidencias = []
    if eh_consulta(texto):
        return novo, pendente, evidencias
    if comando_negado(texto):
        return novo, pendente, evidencias
    if re.search(r"\b(?:talvez|se|caso)\b", normal):
        return novo, {"campo": "intencao"}, evidencias
    if pendente and pendente.get("campo") == "observacao" and pendente.get("prefixo"):
        alvos = [i for i in novo if i["produto"] == pendente["produto"]]
        if len(alvos) == 1 and normal and not re.search(
                r"\b(?:incompreensivel|inaudivel|hmm|nao|quero|adicione|retire|troque)\b", normal):
            obs = texto.strip(" .,!?")
            if not normal.startswith(("sem ", "com ")):
                obs = pendente["prefixo"] + " " + obs
            alvos[0]["observacao"] = obs
            return novo, None, [{"acao": "corrigir", "produto": alvos[0]["produto"],
                                 "quantidade": alvos[0]["quantidade"], "observacao": obs,
                                 "trecho": texto, "contexto": pendente}]
        return novo, pendente, evidencias
    palavras, achados = mencoes(texto, produtos)
    originais = re.findall(r"[^\W_]+", texto, re.UNICODE)
    if re.search(r"\bou\b", normal) and achados:
        return novo, {"campo": "produto", "quantidade": quantidade(normal),
                      "candidatos": list(dict.fromkeys(p.nome for _, _, ps in achados for p in ps))}, evidencias
    if any(re.match(r"nao\b", " ".join(palavras[fim:])) for _, fim, _ in achados):
        return novo, {"campo": "intencao"}, evidencias
    if MEIO_A_MEIO.search(normal):
        # a pizzaria não faz meio a meio: oferece uma pizza de cada sabor, no tamanho dito
        sabores = list(dict.fromkeys(c[0].nome for _, _, c in achados if len(c) == 1 and grupo_tamanho(c[0])))
        ditos = list(dict.fromkeys(t for _, t in tamanhos if t != TAMANHO_INDISPONIVEL))
        return novo, {"campo": "meio_a_meio", "sabores": sabores,
                      "tamanho": ditos[0] if len(ditos) == 1 else None}, evidencias
    if re.search(r"[-+−]\s*\d|\d+[.,]\d|\b(?:meia|meio|metade)\b", texto.lower()):
        duvida = {"campo": "quantidade", "acao": acao_do_trecho(normal)}
        if len(achados) == 1 and len(achados[0][2]) == 1:
            duvida["produto"] = achados[0][2][0].nome
        return novo, duvida, evidencias
    esclarecendo_quantidade = False
    if not achados and pendente and pendente.get("produto"):
        produto = next((p for p in produtos if p.nome == pendente["produto"]), None)
        if produto and pendente["campo"] == "quantidade" and re.fullmatch(NUMERO + r"(?: unidades?)?", normal):
            achados = [(len(palavras), len(palavras), [produto])]
            esclarecendo_quantidade = True
    filtrados = []
    for achado in achados:
        entre = " ".join(palavras[filtrados[-1][1]:achado[0]]) if filtrados else ""
        # "uma calabresa com uma coca" são dois itens; "calabresa sem cebola" é observação.
        # "sem cebola, uma mussarela": a quantidade logo antes do nome abre outro item
        if (re.search(r"\b(?:sem|com)\b", entre) and not re.search(r"\b(?:e|com)\s+(?:" + NUMERO + r"|mais|quero)\b", entre)
                and not re.search(NUMERO + r"$", entre)):
            continue  # Nome usado como ingrediente/observação do produto anterior.
        filtrados.append(achado)
    achados = filtrados
    donos, soltos, errados = _donos_dos_tamanhos(tamanhos, achados, palavras, vocabulario)
    divisoes, usadas = _divisoes_por_tamanho(achados, palavras, soltos)
    soltos = [(posicao, tamanho) for posicao, tamanho in soltos if posicao not in usadas]
    # guardada antes da resposta: "a calabresa é grande" responde e não pode virar mais uma calabresa
    pergunta_de_tamanho = pendente if pendente and pendente.get("campo") == "tamanho" else None
    respondeu_tamanho = False
    if pendente and pendente.get("campo") == "tamanho" and soltos:
        # "grande" responde a "qual o tamanho?"; o resto da fala ("e uma coca") segue normal
        duvida_tamanho, evidencias = _responder_tamanho(novo, pendente, soltos, palavras, texto, produtos, vocabulario)
        respondeu_tamanho = bool(duvida_tamanho or evidencias)
        if respondeu_tamanho:
            pendente = duvida_tamanho
            if pendente or not achados:
                return novo, pendente, evidencias
    falas = set(palavras)
    if (not achados and len(soltos) == 1 and soltos[0][1] != TAMANHO_INDISPONIVEL
            and falas & MUDA_O_TAMANHO and falas <= MUDA_O_TAMANHO | LIGA_O_TAMANHO):
        # "muda pra média", sem citar o produto: vale pro único item do pedido que tem esse tamanho
        tamanho = soltos[0][1]
        alvos = [i for i in novo if any(p.nome == i["produto"] and vocabulario.serve_para(tamanho, p)
                                        for p in produtos)]
        if len(alvos) != 1:
            return novo, {"campo": "qual_muda", "para": tamanho.lower(),
                          "itens": [i["produto"] for i in alvos]}, evidencias
        alvo = alvos[0]
        alvo["tamanho"] = tamanho
        _juntar_iguais(novo)
        return novo, None, [{"acao": "tamanho", "produto": alvo["produto"], "tamanho": tamanho,
                             "quantidade": alvo["quantidade"], "observacao": alvo["observacao"], "trecho": texto}]
    if not achados and re.search(r"\b(?:dessa|desse|daquela|daquele|igual)\b", normal):
        if referencia and len([i for i in atual if i['produto'] == referencia]) == 1:
            produto = next((p for p in produtos if p.nome == referencia), None)
            if produto:
                achados = [(len(palavras), len(palavras), [produto])]
        if not achados:
            return novo, {"campo": "produto", "quantidade": quantidade(normal)}, evidencias

    duvida = None
    # Preserva a quantidade do fragmento desconhecido, separadamente dos itens claros.
    incompleto = re.search(r"(" + NUMERO + r")\s+(?:de\s+)?(?:incompreensivel|inaudivel|ininteligivel|trecho)", normal)
    if incompleto:
        duvida = {"campo": "produto", "quantidade": quantidade(incompleto.group())}

    for fragmento in re.split(r"\s+e\s+(?=" + NUMERO + r"|quero\b)", normal):
        if (quantidade(fragmento) is not None and not mencoes(fragmento, produtos)[1] and not esclarecendo_quantidade
                and not respondeu_tamanho and not (divisoes and re.fullmatch(NUMERO, fragmento.strip()))):
            # "troco pra 100": esse número é dinheiro, não quantidade de produto
            if not re.search(r"\b(?:pix|dinheiro|troco|credito|debito|rua|avenida|av|travessa|alameda|estrada|"
                             r"rodovia)\b",
                             fragmento):
                duvida = {"campo": "produto", "quantidade": quantidade(fragmento)}

    acao = pendente.get("acao", "adicionar") if esclarecendo_quantidade else "adicionar"

    for indice, (inicio, fim, candidatos) in enumerate(achados):
        anterior = achados[indice - 1][1] if indice else 0
        seguinte = achados[indice + 1][0] if indice + 1 < len(achados) else len(palavras)
        prefixo = " ".join(palavras[anterior:inicio])
        # Só a última oração autoriza esta menção ("não quero X, quero Y").
        prefixo = re.split(r"\b(?:e|mas)\b", prefixo)[-1]
        # "sem cebola, uma mussarela": a observação é do item anterior, aqui só vale a quantidade
        if indice and re.search(r"\b(?:sem|com)\b", prefixo) and re.search(NUMERO + r"$", prefixo):
            prefixo = re.search(NUMERO + r"$", prefixo).group()
        # "uma calabresa com uma coca": esse "com" separa dois itens, não é observação.
        prefixo = re.sub(r"^\s*com\s+(?=" + NUMERO + r")", "", prefixo)
        trecho = " ".join(palavras[inicio:fim])
        sufixo = PAGAMENTO_NA_FALA.sub("", " ".join(palavras[fim:seguinte])).strip()
        if indice + 1 < len(achados):
            # a quantidade do próximo item não é parte da observação deste
            sufixo = re.sub(r"\s*(?:\b(?:com|e)\s+)?" + NUMERO + r"$", "", sufixo).strip()
        qtd = quantidade(prefixo)
        acao = acao_do_trecho(prefixo, acao)
        # A quantidade pendente é de um item a acrescentar: não vale para "tire as cocas".
        if qtd is None and pendente and pendente.get("campo") == "produto" and len(achados) == 1 and acao == "adicionar":
            qtd = pendente.get("quantidade")
        permitido = re.sub(NUMERO, "", prefixo)
        permitido = re.sub(r"\b(?:eu|quero|queria|gostaria|de|a|o|as|os|mais|uma|um|"
                           + VERBOS_DE_ADICIONAR + r"|" + VERBOS_DE_REMOVER + r"|manda|mande|pedir|ai|"
                           r"pode|poderia|por|favor|sim|nao|na|verdade|so|apenas|dessa|desse|daquela|daquele|igual|corrija|corrigir|"
                           r"altere|alterar|altera|deixe|deixa|mude|muda|"
                           r"me|ve|da|traz|traga|vou|querer|ser|vai|vamos|ah|oi|ola|outra|outro|outras|outros|"
                           r"boa|bom|noite|tarde|dia|entao|hoje|tambem|agora|pra|para|mim|sao|fica|ficam|esqueci|faltou)\b", "", permitido).strip()
        if permitido or re.match(r"e\s+(?!so isso|uma?\b|duas?\b|dois\b|tres\b|\d+\b|(?:"
                                 + VERBOS_DE_ADICIONAR + r"|" + VERBOS_DE_REMOVER
                                 + r"|quero|queria|manda|mande|me ve|traz|traga|troca|troque)\b)", sufixo):
            duvida = {"campo": "intencao"}
            continue
        no_pedido = [p for p in candidatos if any(i["produto"] == p.nome for i in atual)]
        esperando = bool(pendente and pendente.get("campo") == "tamanho" and no_pedido
                         and pendente.get("produto") == no_pedido[0].nome)
        if (len(candidatos) > 1 and len(no_pedido) == 1 and qtd is None and acao == "adicionar"
                and (esperando or re.search(r"\b(?:a|o)(?:\s+d[aeo])?\s*$", prefixo))):
            # "a de catupiry": o artigo aponta o item que já está no pedido; a pergunta aberta continua
            if pendente and pendente.get("campo") == "tamanho":
                duvida = {**pendente, "referencia": True}
            continue
        if len(candidatos) != 1:
            duvida = {"campo": "produto", "quantidade": qtd or 1,
                      "candidatos": [p.nome for p in candidatos], "trecho": trecho}
            cauda = re.split(r"\b(?:e|no|pago|por favor)\b", sufixo)[0].strip()
            if cauda and not re.match(r"(?:sem|com)\b", cauda):
                duvida = {"campo": "produto", "quantidade": qtd or 1,
                          "nao_encontrado": trecho + " " + cauda}
            continue
        produto = candidatos[0]
        if indice in divisoes and acao == "adicionar":
            partes = divisoes[indice]
            total = sum(q for q, _ in partes)
            if (qtd or total) == total and all(vocabulario.serve_para(t, produto) for _, t in partes):
                novos = partes
            else:
                # "duas calabresas, uma grande e duas médias": a conta não fecha, então entra sem tamanho e pergunta
                novos = [(qtd or total, None)]
                duvida = {"campo": "tamanho", "produto": produto.nome, "misto": True}
            for q, t in novos:
                alvo = next((i for i in novo if i["produto"] == produto.nome and i["observacao"] is None
                             and i.get("tamanho") == t), None)
                if alvo:
                    alvo["quantidade"] += q
                else:
                    novo.append({"produto": produto.nome, "quantidade": q, "observacao": None,
                                 "preco": produto.preco, "tamanho": t})
                evidencias.append({"acao": "adicionar", "produto": produto.nome, "quantidade": q, "tamanho": t,
                                   "observacao": None, "trecho": prefixo + " " + trecho + " " + sufixo})
            continue
        # Um nome parcial não autoriza ignorar a variante ou o volume ditos depois.
        cauda = sufixo
        nome_radical = " ".join(radical(p) for p in _normalizar(produto.nome).split())
        trecho_radical = " ".join(radical(p) for p in trecho.split())
        restante = nome_radical.partition(trecho_radical)[2].strip() if trecho_radical else ""
        if restante:
            tamanho = r"^(?:de\s+)?" + r"\s+".join(re.escape(p) + "s?" for p in restante.split()) + r"\b"
            cauda = re.sub(tamanho, "", cauda).strip()
        # "coca 2 litros": só o volume que está no nome; "coca 600 ml" continua sendo outro produto.
        volume = re.match(r"(\d+)\s*(litros?|ml)\b", cauda)
        if volume and "{} {}".format(volume[1], radical(volume[2])) in nome_radical:
            cauda = cauda[volume.end():].strip()
        if cauda and not re.match(r"(?:e|mas|sem|com|pago|pagamento|entrega|por favor|so isso|pra mim|para mim|hoje|"
                                  r"vou pagar|quero pagar|pode ser|vai ser|fica|ficam|seja|sejam|sera|sao|tambem)\b",
                                  cauda):
            duvida = {"campo": "produto", "quantidade": qtd or 1,
                      "nao_encontrado": trecho + " " + sufixo}
            continue
        existentes = [i for i in novo if i["produto"] == produto.nome]
        if re.fullmatch(r"nao\s+(?:" + NUMERO + r")", prefixo.strip()) and existentes:
            # "não, dois guaranás": corrige a quantidade do que acabou de ser anotado
            acao = "corrigir"
        elif re.search(r"\bnao\b", prefixo) and not REMOVER.search(prefixo):
            continue
        if indice in errados:
            duvida = {"campo": "produto", "quantidade": qtd or 1,
                      "nao_encontrado": "{} {}".format(trecho, errados[indice].lower())}
            continue
        # Só pizza e refrigerante têm tamanho: "coca grande" pede o tamanho de refrigerante depois.
        tamanho = None
        ditos = set(donos.get(indice, [])) if grupo_tamanho(produto) else set()
        if TAMANHO_INDISPONIVEL in ditos or len(ditos) > 1:
            duvida = {"campo": "tamanho", "produto": produto.nome,
                      ("indisponivel" if TAMANHO_INDISPONIVEL in ditos else "misto"): True}
        elif ditos:
            tamanho = ditos.pop()
        elif grupo_tamanho(produto) and acao == "adicionar" and re.search(r"\bmais\b", prefixo):
            # "mais uma margherita" é igual à que já está no pedido, se só houver um tamanho dela
            ja_pedidos = {i.get("tamanho") for i in existentes if i.get("tamanho")}
            if len(ja_pedidos) == 1:
                tamanho = ja_pedidos.pop()
        if tamanho and acao == "remover":
            # "tire a calabresa grande" mexe só na grande, mesmo com uma média no pedido
            existentes = [i for i in existentes if i.get("tamanho") == tamanho]
        sem_tamanho = [i for i in existentes if not i.get("tamanho")]
        pergunta_deste = (pergunta_de_tamanho or {}).get("produto") == produto.nome
        mais_uma = re.search(r"\b(?:mais|outra|outro|outras|outros)\b", prefixo)
        quantos_sem_tamanho = sum(i["quantidade"] for i in sem_tamanho)
        # "uma calabresa grande" logo depois de "qual o tamanho da calabresa?" responde a pergunta
        if (tamanho and acao == "adicionar" and sem_tamanho and not mais_uma
                and ((pergunta_deste and qtd in (None, quantos_sem_tamanho))
                     or (qtd is None and not PEDE_MAIS_UM.search(prefixo)))):
            # "a calabresa é grande": é o tamanho da pizza já anotada, não mais uma pizza
            for item in sem_tamanho:
                item["tamanho"] = tamanho
            _juntar_iguais(novo)
            evidencias.append({"acao": "tamanho", "produto": produto.nome, "tamanho": tamanho,
                               "quantidade": sum(i["quantidade"] for i in sem_tamanho),
                               "observacao": sem_tamanho[0]["observacao"], "trecho": prefixo + " " + trecho})
            continue
        # "a calabresa é média", "quero a calabresa média": o artigo definido aponta a pizza já anotada em outro
        # tamanho, então ela muda de tamanho. "uma calabresa média" continua sendo mais uma pizza
        aponta_a_anotada = (tamanho and acao == "adicionar" and existentes and not sem_tamanho and not mais_uma
                            and qtd is None and re.search(r"\b(?:a|o|as|os)\s*$", prefixo))
        if aponta_a_anotada and len(existentes) > 1:
            # duas calabresas de tamanhos diferentes: nao da pra saber qual muda, e somar uma terceira seria pior
            duvida = {"campo": "intencao"}
            continue
        if aponta_a_anotada:
            alvo = existentes[0]
            alvo["tamanho"] = tamanho
            _juntar_iguais(novo)
            evidencias.append({"acao": "tamanho", "produto": produto.nome, "tamanho": tamanho,
                               "quantidade": alvo["quantidade"], "observacao": alvo["observacao"],
                               "trecho": prefixo + " " + trecho})
            continue
        if pergunta_deste and not tamanho and qtd is None and acao == "adicionar" and not PEDE_MAIS_UM.search(prefixo):
            # repetir o nome da pizza não pede outra pizza: ou já respondeu o tamanho, ou ainda falta
            if not respondeu_tamanho:
                duvida = pendente
            continue
        if acao == "remover":
            # "Tire cebola da pizza" não é autorização para tirar a pizza.
            resto = REMOVER.sub("", prefixo).strip()
            resto = re.sub(NUMERO, "", resto)
            if re.sub(r"\b(?:a|o|as|os|uma|um|sim|nao|pode|poderia|por|favor|eu|quero|queria|me|entao|agora|mais)\b",
                      "", resto).strip():
                duvida = {"campo": "observacao", "produto": produto.nome}
                continue
            if not existentes:
                duvida = {"campo": "fora_do_pedido", "produto": produto.nome}
                continue
            if len(existentes) != 1 or (qtd is not None and qtd > existentes[0]["quantidade"]):
                duvida = {"campo": "quantidade", "produto": produto.nome, "acao": "remover"}
                continue
            alvo = existentes[0]
            retirar = qtd if qtd is not None else alvo["quantidade"]
            if retirar <= 0:
                duvida = {"campo": "quantidade", "produto": produto.nome, "acao": "remover"}
                continue
            alvo["quantidade"] -= retirar
            if not alvo["quantidade"]:
                novo.remove(alvo)
            evidencias.append({"acao": "remover", "produto": produto.nome, "tamanho": alvo.get("tamanho"),
                               "quantidade": retirar, "trecho": prefixo + " " + trecho})
            continue

        observacao = None
        obs = re.search(r"\b(sem|com)\s+(.+)", sufixo)
        obs_incompleta = re.search(r"\b(sem|com)\s*(?:incompreensivel|inaudivel|trecho)?$", sufixo)
        if obs_incompleta:
            duvida = {"campo": "observacao", "produto": produto.nome, "prefixo": obs_incompleta[1]}
        elif obs:
            observacao = re.split(
                r"\s+(?:e\s+(?:" + NUMERO + r")|no\s+(?:pix|credito|debito|cartao)|"
                r"pago|pagamento|so isso|e so isso|entrega|por favor)\b", obs.group(), maxsplit=1)[0].strip()
            inicio_obs = fim + len(sufixo[:obs.start()].split())
            observacao = " ".join(originais[inicio_obs:inicio_obs + len(observacao.split())])
        corrigindo = acao == "corrigir"
        if existentes and observacao and qtd is None and not re.search(r"\b(?:mais|adicione|acrescente|quero)\b", prefixo):
            corrigindo = True
        if qtd is None:
            qtd = existentes[0]["quantidade"] if corrigindo and len(existentes) == 1 else 1
        if qtd <= 0:
            duvida = {"campo": "quantidade", "produto": produto.nome, "acao": acao}
            continue
        if corrigindo and existentes:
            if len(existentes) != 1:
                duvida = {"campo": "observacao", "produto": produto.nome}
                continue
            existentes[0]["quantidade"] = qtd
            if observacao:
                existentes[0]["observacao"] = observacao
            if tamanho:
                existentes[0]["tamanho"] = tamanho
            tamanho = existentes[0].get("tamanho")
        else:
            alvo = next((i for i in existentes if i["observacao"] == observacao
                         and i.get("tamanho") == tamanho), None)
            if alvo:
                alvo["quantidade"] += qtd
            else:
                novo.append({"produto": produto.nome, "quantidade": qtd,
                             "observacao": observacao, "preco": produto.preco, "tamanho": tamanho})
        evidencias.append({"acao": "corrigir" if corrigindo else "adicionar",
                           "produto": produto.nome, "quantidade": qtd, "tamanho": tamanho,
                           "observacao": observacao, "trecho": prefixo + " " + trecho + " " + sufixo})

    if not achados and not respondeu_tamanho:
        # Pagamento, endereço e fechamento são tratados pelo roteiro, sem reconstruir itens.
        if not FECHAR.search(normal) and not re.search(
                r"\b(?:pix|pics|picks|piques|pixe|dinheiro|troco|cartao|credito|debito|endereco|rua|avenida|av|"
                r"travessa|alameda|estrada|rodovia)\b", normal):
            duvida = pendente or {"campo": "produto", "quantidade": quantidade(normal)}
            desconhecido = re.sub(r"^(?:(?:eu|quero|queria|uma?|duas?|dois|tres|de)\s+)+", "", normal)
            if not pendente and desconhecido and not re.search(r"\b(?:incompreensivel|inaudivel|hmm|trecho)\b", desconhecido):
                duvida["nao_encontrado"] = desconhecido
        else:
            duvida = pendente
    return novo, duvida, evidencias
