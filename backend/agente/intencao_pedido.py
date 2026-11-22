"""Evidência da fala para editar o rascunho; o JSON do modelo não é autorização.

shortcut: comandos que não cabem nesta gramática conservadora são esclarecidos,
não aproximados. Amplie com uma regressão de fala real ao aceitar outra construção.
"""

import re
from copy import deepcopy
from functools import lru_cache
from difflib import get_close_matches

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
                     r"cancele|cancelar|cancela")
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
CORRIGIR = re.compile(r"\b(?:na verdade|so|apenas|corrija|corrigir|altere|alterar|deixe|mude)\b")


# Parecem nomes do cardápio, mas são palavras do dia a dia: "quanto" não é "quatro queijos".
# Os verbos também: a comparação aproximada levava "cancela" para "canela" e "anota" para "fanta".
NAO_E_PRODUTO = {"quanto", "quanta", *VERBOS_DE_ADICIONAR.split("|"), *VERBOS_DE_REMOVER.split("|")}
# Grafias que ficam longe demais do nome para a comparação aproximada.
GRAFIAS = {"calabreza": "calabresa", "mozarela": "mussarela", "muzarela": "mussarela",
           "muzzarela": "mussarela", "mozzarela": "mussarela", "mozzarella": "mussarela"}
# Fala inteira que encerra o pedido. A cortesia ("obrigado") é retirada antes de comparar.
FALAS_DE_FECHAR = {
    "e so isso", "so isso", "so isso mesmo", "e so isso mesmo", "e isso", "e isso ai", "e isso mesmo",
    "e so", "so", "era isso", "era so isso", "por enquanto e so", "por enquanto e isso",
    "pode fechar", "fechar", "fecha", "fecha o pedido", "fechar o pedido", "pode fechar o pedido",
    "finalizar", "finaliza", "pode finalizar", "quero finalizar", "finaliza o pedido", "terminei",
    "acabei", "acabou", "mais nada", "nada mais", "nao quero mais nada", "ta bom assim", "esta bom assim",
    "quero pagar", "vou pagar", "pagar", "pode cobrar", "encerrar", "pode encerrar",
}


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
    return re.sub(r"\b4\s+queijos?\b", "quatro queijos", texto, flags=re.IGNORECASE)


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


def interpretar(texto, produtos, atual, pendente=None, referencia=None, vocabulario=TAMANHOS_BASE):
    """Retorna (rascunho, pendência de campo, evidências) sem efeitos externos."""
    texto = _numero_do_nome(texto)
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
        if re.search(r"\b(?:sem|com)\b", entre) and not re.search(r"\b(?:e|com)\s+(?:" + NUMERO + r"|mais|quero)\b", entre):
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
            return novo, {"campo": "qual_muda", "tamanho": tamanho,
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
            if not re.search(r"\b(?:pix|dinheiro|credito|debito|rua|avenida|av|travessa|alameda|estrada|rodovia)\b",
                             fragmento):
                duvida = {"campo": "produto", "quantidade": quantidade(fragmento)}

    acao = pendente.get("acao", "adicionar") if esclarecendo_quantidade else "adicionar"

    for indice, (inicio, fim, candidatos) in enumerate(achados):
        anterior = achados[indice - 1][1] if indice else 0
        seguinte = achados[indice + 1][0] if indice + 1 < len(achados) else len(palavras)
        prefixo = " ".join(palavras[anterior:inicio])
        # Só a última oração autoriza esta menção ("não quero X, quero Y").
        prefixo = re.split(r"\b(?:e|mas)\b", prefixo)[-1]
        # "uma calabresa com uma coca": esse "com" separa dois itens, não é observação.
        prefixo = re.sub(r"^\s*com\s+(?=" + NUMERO + r")", "", prefixo)
        trecho = " ".join(palavras[inicio:fim])
        sufixo = PAGAMENTO_NA_FALA.sub("", " ".join(palavras[fim:seguinte])).strip()
        if indice + 1 < len(achados):
            sufixo = re.sub(r"\s*\bcom\s+" + NUMERO + r"$", "", sufixo).strip()
        qtd = quantidade(prefixo)
        acao = acao_do_trecho(prefixo, acao)
        # A quantidade pendente é de um item a acrescentar: não vale para "tire as cocas".
        if qtd is None and pendente and pendente.get("campo") == "produto" and len(achados) == 1 and acao == "adicionar":
            qtd = pendente.get("quantidade")
        permitido = re.sub(NUMERO, "", prefixo)
        permitido = re.sub(r"\b(?:eu|quero|queria|gostaria|de|a|o|as|os|mais|uma|um|"
                           + VERBOS_DE_ADICIONAR + r"|" + VERBOS_DE_REMOVER + r"|manda|mande|pedir|ai|"
                           r"pode|poderia|por|favor|sim|nao|na|verdade|so|apenas|dessa|desse|daquela|daquele|igual|corrija|corrigir|"
                           r"altere|alterar|deixe|mude|"
                           r"me|ve|da|traz|traga|vou|querer|ser|vai|vamos|ah|oi|ola|outra|outro|outras|outros|"
                           r"boa|bom|noite|tarde|dia|entao|hoje|tambem|agora|pra|para|mim|sao|fica|ficam)\b", "", permitido).strip()
        if permitido or re.match(r"e\s+(?!so isso|uma?\b|duas?\b|dois\b|tres\b|\d+\b)", sufixo):
            duvida = {"campo": "intencao"}
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
                                  r"vou pagar|quero pagar|pode ser|vai ser|fica|ficam|seja|sejam|sera|sao)\b", cauda):
            duvida = {"campo": "produto", "quantidade": qtd or 1,
                      "nao_encontrado": trecho + " " + sufixo}
            continue
        existentes = [i for i in novo if i["produto"] == produto.nome]
        if re.search(r"\bnao\b", prefixo) and not REMOVER.search(prefixo):
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
            if re.sub(r"\b(?:a|o|as|os|uma|um|sim|nao|pode|poderia|por|favor|eu|quero|queria|me|entao|agora)\b",
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
                r"\b(?:pix|pics|picks|piques|pixe|dinheiro|cartao|credito|debito|endereco|rua|avenida|av|travessa|"
                r"alameda|estrada|rodovia)\b", normal):
            duvida = pendente or {"campo": "produto", "quantidade": quantidade(normal)}
            desconhecido = re.sub(r"^(?:(?:eu|quero|queria|uma?|duas?|dois|tres|de)\s+)+", "", normal)
            if not pendente and desconhecido and not re.search(r"\b(?:incompreensivel|inaudivel|hmm|trecho)\b", desconhecido):
                duvida["nao_encontrado"] = desconhecido
        else:
            duvida = pendente
    return novo, duvida, evidencias
