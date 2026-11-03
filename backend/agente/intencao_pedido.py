"""Evidência da fala para editar o rascunho; o JSON do modelo não é autorização.

shortcut: comandos que não cabem nesta gramática conservadora são esclarecidos,
não aproximados. Amplie com uma regressão de fala real ao aceitar outra construção.
"""

import re
from copy import deepcopy

from repositorio import _normalizar


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
    r"\b(?:ultim[oa]s? (?:vez|pedidos?|compras?)|pedidos? anteriore?s?|meu historico|"
    r"historico de pedidos|meus pedidos|o que (?:eu )?(?:ja )?pedi|ja pedi)\b"
)
CONSULTA_RECOMENDACAO = re.compile(
    r"\b(?:recomenda\w*|sugere|sugest\w*|indica|de sempre|mais peco|costumo pedir|"
    r"minha preferida|meu preferido|minha favorita|meu favorito)\b"
)
FECHAR = re.compile(r"\b(?:e so isso|so isso|pode fechar|fechar o pedido|finalizar|terminei)\b")
REMOVER = re.compile(r"\b(?:tire|tira|tirar|retire|retira|retirar|remova|remover|exclua|nao quero)\b")
CORRIGIR = re.compile(r"\b(?:na verdade|so|apenas|corrija|corrigir|altere|alterar|deixe|mude)\b")


def quantidade(texto):
    encontrados = re.findall(NUMERO, texto)
    if not encontrados:
        return None
    valor = encontrados[-1]
    return int(valor) if valor.isdigit() else NUMEROS[valor]


def radical(palavra):
    palavra = "mineral" if palavra == "minerais" else palavra.removesuffix("s")
    # Grafia observada no Whisper real; se ambos os nomes existirem, fica ambíguo.
    return "calabresa" if palavra == "calabreza" else palavra


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
    if re.search(r"\b(?:quero|queria|adicione|adicionar|acrescente|acrescentar|inclua|coloque|mais)\b", texto):
        return "adicionar"
    return anterior


def mencoes(texto, produtos):
    """Maior trecho contíguo do nome; nunca resolve um nome com vários candidatos."""
    palavras = _normalizar(texto).split()
    radicais = [radical(p) for p in palavras]
    nomes = [(p, [radical(t) for t in _normalizar(p.nome).split()]) for p in produtos]
    ignorar = {"de", "do", "da", "com", "sem", "e", "o", "a", "litro", "ml"}
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
    comando = re.match(r"(?:pode|poderia) (?:adicionar|acrescentar|retirar|trocar|substituir)\b", normal)
    return bool(CONSULTA.search(normal) or CONSULTA_HISTORICO.search(normal) or
                CONSULTA_RECOMENDACAO.search(normal) or normal.startswith("se ") or
                ("?" in texto and not comando))


def cardapio_completo(texto):
    normal = _normalizar(texto)
    return bool(re.search(r"\b(?:cardapio|menu)\b", normal) or
                re.search(r"\b(?:todos|todas)\b.*\b(?:produtos|opcoes|precos)\b", normal))


def interpretar(texto, produtos, atual, pendente=None, referencia=None):
    """Retorna (rascunho, pendência de campo, evidências) sem efeitos externos."""
    normal = _normalizar(texto)
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
        if re.search(r"\b(?:sem|com)\b", entre) and not re.search(r"\be\s+(?:" + NUMERO + r"|mais|quero)\b", entre):
            continue  # Nome usado como ingrediente/observação do produto anterior.
        filtrados.append(achado)
    achados = filtrados
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
        if quantidade(fragmento) is not None and not mencoes(fragmento, produtos)[1] and not esclarecendo_quantidade:
            if not re.search(r"\b(?:pix|dinheiro|credito|debito|rua|avenida)\b", fragmento):
                duvida = {"campo": "produto", "quantidade": quantidade(fragmento)}

    acao = pendente.get("acao", "adicionar") if esclarecendo_quantidade else "adicionar"

    for indice, (inicio, fim, candidatos) in enumerate(achados):
        anterior = achados[indice - 1][1] if indice else 0
        seguinte = achados[indice + 1][0] if indice + 1 < len(achados) else len(palavras)
        prefixo = " ".join(palavras[anterior:inicio])
        # Só a última oração autoriza esta menção ("não quero X, quero Y").
        prefixo = re.split(r"\b(?:e|mas)\b", prefixo)[-1]
        trecho = " ".join(palavras[inicio:fim])
        sufixo = " ".join(palavras[fim:seguinte])
        qtd = quantidade(prefixo)
        if qtd is None and pendente and pendente.get("campo") == "produto" and len(achados) == 1:
            qtd = pendente.get("quantidade")
        acao = acao_do_trecho(prefixo, acao)
        permitido = re.sub(NUMERO, "", prefixo)
        permitido = re.sub(r"\b(?:eu|quero|queria|gostaria|de|a|o|as|os|mais|uma|um|"
                           r"adicione|adicionar|acrescente|acrescentar|inclua|coloque|manda|mande|"
                           r"pode|poderia|por|favor|sim|nao|na|verdade|so|apenas|dessa|desse|daquela|daquele|igual|corrija|corrigir|"
                           r"altere|alterar|deixe|mude|tire|tira|tirar|retire|retira|retirar|"
                           r"remova|remover|exclua)\b", "", permitido).strip()
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
        # Um nome parcial não autoriza ignorar a variante ou o volume ditos depois.
        cauda = sufixo
        nome_radical = " ".join(radical(p) for p in _normalizar(produto.nome).split())
        trecho_radical = " ".join(radical(p) for p in trecho.split())
        restante = nome_radical.partition(trecho_radical)[2].strip() if trecho_radical else ""
        if restante:
            tamanho = r"^(?:de\s+)?" + r"\s+".join(re.escape(p) + "s?" for p in restante.split()) + r"\b"
            cauda = re.sub(tamanho, "", cauda).strip()
        if cauda and not re.match(r"(?:e|mas|sem|com|pago|pagamento|entrega|por favor|so isso)\b|no (?:pix|credito|debito|cartao)\b", cauda):
            duvida = {"campo": "produto", "quantidade": qtd or 1,
                      "nao_encontrado": trecho + " " + sufixo}
            continue
        existentes = [i for i in novo if i["produto"] == produto.nome]
        if re.search(r"\bnao\b", prefixo) and not REMOVER.search(prefixo):
            continue
        if acao == "remover":
            # "Tire cebola da pizza" não é autorização para tirar a pizza.
            resto = REMOVER.sub("", prefixo).strip()
            resto = re.sub(NUMERO, "", resto)
            if re.sub(r"\b(?:a|o|as|os|uma|um|sim|nao)\b", "", resto).strip():
                duvida = {"campo": "observacao", "produto": produto.nome}
                continue
            if not existentes:
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
            evidencias.append({"acao": "remover", "produto": produto.nome,
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
        else:
            alvo = next((i for i in existentes if i["observacao"] == observacao), None)
            if alvo:
                alvo["quantidade"] += qtd
            else:
                novo.append({"produto": produto.nome, "quantidade": qtd,
                             "observacao": observacao, "preco": produto.preco})
        evidencias.append({"acao": "corrigir" if corrigindo else "adicionar",
                           "produto": produto.nome, "quantidade": qtd,
                           "observacao": observacao, "trecho": prefixo + " " + trecho + " " + sufixo})

    if not achados:
        # Pagamento, endereço e fechamento são tratados pelo roteiro, sem reconstruir itens.
        if not FECHAR.search(normal) and not re.search(r"\b(?:pix|dinheiro|cartao|credito|debito|endereco|rua|avenida)\b", normal):
            duvida = pendente or {"campo": "produto", "quantidade": quantidade(normal)}
            desconhecido = re.sub(r"^(?:(?:eu|quero|queria|uma?|duas?|dois|tres|de)\s+)+", "", normal)
            if not pendente and desconhecido and not re.search(r"\b(?:incompreensivel|inaudivel|hmm|trecho)\b", desconhecido):
                duvida["nao_encontrado"] = desconhecido
        else:
            duvida = pendente
    return novo, duvida, evidencias
