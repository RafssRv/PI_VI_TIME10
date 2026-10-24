# roteiro da chamada: identifica o cliente pelo cpf (cadastra se ele nao tiver conta) e
# depois monta e grava o pedido.
# quem consulta e grava no banco eh sempre o codigo, chamando as funcoes do repositorio.
# o llama so entra depois q o cliente ta identificado: ele conversa e devolve um json com o
# q entendeu do pedido, o python confere tudo contra o cardapio, le o resumo pro cliente e so
# grava quando ele confirma. o modelo nunca encosta no banco (nada de sql escrito por ele).
#
# uma instancia por chamada (o main.py cria uma por websocket), pq ela guarda em q etapa
# a conversa ta e o q o cliente ja disse.

import json
import re
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from agente.controle_pedido import ControlePedido, ErroPedido, ProdutoCardapio

from sqlalchemy.exc import SQLAlchemyError

import repositorio
from repositorio import _normalizar

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

FRASE_PEDE_CPF = "Para começar, me diga o seu CPF, por favor."
FRASE_ERRO_BANCO = "Tive um problema para consultar o sistema. Pode repetir, por favor?"
FRASE_PEDE_PAGAMENTO = "Como você vai pagar? Pix, dinheiro, cartão de crédito ou débito?"

PAGAMENTO_FALADO = {
    "pix": "no Pix",
    "dinheiro": "em dinheiro",
    "cartao_credito": "no cartão de crédito",
    "cartao_debito": "no cartão de débito",
}

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


def _prompt_base():
    return (Path(__file__).parent / "agente" / "prompt_sistema.txt").read_text(encoding="utf-8")


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
        # os dois podem vir de fora pros testes: a sessao do banco de teste e um llama de mentira
        self._abrir_sessao = abrir_sessao
        self._conversar = conversar
        self.etapa = "inicio"
        self.cliente_id = None
        self.nome = None
        self.endereco_do_cadastro = None
        self.cadastro = {}
        self.historico = []
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
        self._troca_pendente = False
        self._pendencia_antes_da_troca = None

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
        return etapas[self.etapa](texto)

    # --- banco ---

    def _sessao(self):
        if self._abrir_sessao is None:
            from database import SessionLocal
            self._abrir_sessao = SessionLocal
        return self._abrir_sessao()

    # --- identificacao ---

    def _inicio(self, texto):
        # tem gente q ja chega falando o cpf, ai nem precisa pedir
        if len(extrair_digitos(texto)) >= 11:
            return self._receber_cpf(texto)
        self.etapa = "aguardando_cpf"
        return "Olá! Bem-vindo à pizzaria. " + FRASE_PEDE_CPF

    def _receber_cpf(self, texto):
        self.etapa = "aguardando_cpf"
        digitos = extrair_digitos(texto)
        if len(digitos) != 11:
            return "Não consegui entender o CPF. Pode falar os onze números, por favor?"

        db = self._sessao()
        try:
            cliente = repositorio.buscar_cliente_por_cpf(db, digitos)
        except ValueError:
            # digito verificador nao bate: quase sempre eh o whisper q ouviu um numero errado
            return "Esse CPF parece inválido. Pode repetir devagar, por favor?"
        except Exception as erro:
            print(f"[atendimento] erro ao buscar cliente: {erro}")
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        if cliente:
            self._identificar(cliente.id, cliente.nome, cliente.endereco)
            return "Achei seu cadastro, {}! O que vai querer hoje?".format(self._primeiro_nome())

        self.cadastro = {"cpf": digitos}
        self.etapa = "oferecendo_cadastro"
        return "Não encontrei nenhuma conta com esse CPF. Deseja criar uma conta agora?"

    def _receber_aceite(self, texto):
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

    def _receber_nome(self, texto):
        nome = extrair_nome(texto)
        if not nome:
            return "Não entendi o seu nome. Pode repetir, por favor?"
        self.cadastro["nome"] = nome
        self.etapa = "aguardando_telefone"
        return "Prazer, {}! Qual é o seu telefone com DDD?".format(nome.split()[0])

    def _receber_telefone(self, texto):
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
        except ValueError as erro:
            # cpf q alguem cadastrou no meio tempo, nome grande demais...
            print(f"[atendimento] cadastro recusado: {erro}")
            self.cadastro = {}
            self.etapa = "aguardando_cpf"
            return "Não consegui criar a conta com esses dados. " + FRASE_PEDE_CPF
        except Exception as erro:
            print(f"[atendimento] erro ao cadastrar: {erro}")
            return FRASE_ERRO_BANCO
        finally:
            db.close()

        self.cadastro = {}
        self._identificar(cliente_id, nome, endereco)
        return "Pronto, {}, sua conta foi criada! O que vai querer hoje?".format(
            self._primeiro_nome())

    def _identificar(self, cliente_id, nome, endereco):
        self.cliente_id = cliente_id
        self.nome = nome
        self.endereco_do_cadastro = endereco
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
            return self._montar_pedido_com(db, texto)
        except SQLAlchemyError as erro:
            # erro do llama (ollama fechado) sobe de proposito: o turno_de_voz avisa na tela
            print(f"[atendimento] erro no banco ao montar o pedido: {erro}")
            return FRASE_ERRO_BANCO
        finally:
            db.close()

    def _montar_pedido_com(self, db, texto):
        normalizado = _normalizar(texto).strip()
        if self._troca_pendente:
            if normalizado in {"cancele a troca", "cancelar a troca", "desisti da troca"}:
                self._troca_pendente = False
                self._pendencia = self._pendencia_antes_da_troca
                self._pendencia_antes_da_troca = None
                if self._controle:
                    self._controle.definir_pendencia(self._pendencia)
                fala = self._fechar_pedido()
                self.historico.extend([{"role": "user", "content": texto},
                                       {"role": "assistant", "content": fala}])
                return fala
            if not PEDIDO_DE_TROCA.search(normalizado):
                return self._pendencia
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
            fala = self._pendencia or self._fechar_pedido()
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            return fala
        # Não pedir ao modelo para inventar condições que o cadastro não fornece.
        if set(normalizado.split()) & {"taxa", "frete", "gratis", "gratuita", "gratuito",
                                       "prazo", "desconto", "demora"}:
            fala = "A pizzaria precisa confirmar a taxa, o prazo de entrega e se há desconto."
            self.historico.extend([{"role": "user", "content": texto},
                                   {"role": "assistant", "content": fala}])
            return fala
        if confirmacao_explicita(texto) or normalizado in {"e so isso", "so isso", "pode fechar", "terminei"}:
            return self._fechar_pedido()
        cardapio = repositorio.listar_cardapio(db)

        turno = {"role": "user", "content": texto}
        mensagens = [{"role": "system", "content": self._prompt_do_pedido(cardapio)}]
        # Uma fala ainda não interpretada impede confirmar o carrinho anterior,
        # inclusive se o Ollama falhar ou devolver uma resposta inválida.
        self._pendencia = "Desculpe, não entendi. Pode repetir?"
        self._token_resumo = None
        if self._controle:
            self._controle.definir_pendencia(self._pendencia)
        bruto = self._carregar_llama()(mensagens + self.historico + [turno], formato=ESQUEMA_DO_PEDIDO)

        try:
            dados = json.loads(bruto)
            if (not isinstance(dados, dict) or not isinstance(dados.get("itens"), list)
                    or not isinstance(dados.get("resposta"), str)
                    or type(dados.get("fechar")) is not bool
                    or "endereco" not in dados
                    or (dados["endereco"] is not None and not isinstance(dados["endereco"], str))):
                raise ValueError("estrutura incompleta ou inválida")
        except ValueError as erro:
            print(f"[atendimento] resposta inválida do modelo: {erro}")
            return self._pendencia

        self.historico.append(turno)
        problemas = self._atualizar_carrinho(db, dados.get("itens") or [])
        # o pagamento sai da fala do cliente, nao do llama: testando, o modelo transformava
        # "no cartao" em "credito" sozinho, e cobrar na modalidade errada eh pior q perguntar
        problemas += self._atualizar_pagamento(texto)
        self._pendencia = " ".join(problemas) or None
        if self._controle:
            self._controle.definir_pendencia(self._pendencia)

        endereco = str(dados.get("endereco") or "").strip()
        if len(endereco) >= 5 and _normalizar(endereco) not in ("null", "none"):
            self.endereco_entrega = endereco

        if problemas:
            # o q o python achou de errado vale mais q a frase do modelo, q pode ter
            # confirmado um produto q nem existe
            fala = " ".join(problemas)
        elif self.carrinho or dados.get("fechar") is True:
            # Nunca deixe a frase livre do modelo anunciar itens ou totais divergentes.
            fala = self._fechar_pedido()
        else:
            fala = str(dados.get("resposta") or "").strip() or "O que mais vai querer?"
            if "?" in fala and not self.carrinho:
                self._pendencia = fala
                if self._controle:
                    self._controle.definir_pendencia(fala)

        self.historico.append({"role": "assistant", "content": fala})
        return fala

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
            return self._pendencia
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
                return "Posso confirmar o pedido? Responda sim ou não."
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
        except ValueError as erro:
            # o cardapio mudou entre o resumo e o sim (produto desativado, por exemplo)
            print(f"[atendimento] pedido recusado pelo repositorio: {erro}")
            self.etapa = "identificado"
            problemas = self._atualizar_carrinho(db, self.carrinho)
            self._pendencia = " ".join(problemas) or None
            if problemas:
                return self._pendencia
            return "O cardápio mudou; confira os valores atualizados. " + self._fechar_pedido()
        except Exception as erro:
            # continua confirmando: se o cliente disser sim de novo, tenta gravar de novo
            print(f"[atendimento] erro ao salvar o pedido: {erro}")
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
            "Você é o atendente de telefone de uma pizzaria e está anotando o pedido de "
            "{}.".format(self.nome),
            "Responda sempre com um JSON com estes campos:",
            '- "resposta": o que você vai falar para o cliente, em português do Brasil. No máximo '
            "duas frases curtas, sem listas, sem emojis e sem markdown, porque será lido em voz "
            "alta. Nunca diga que o pedido foi registrado ou confirmado: quem faz isso é o sistema.",
            '- "itens": o pedido COMPLETO, já com a mudança que o cliente acabou de pedir. Parta do '
            "pedido atual abaixo, acrescente, troque ou tire o que ele disse e mantenha o resto. "
            "Use o nome exato do cardápio. Se o cliente foi vago (por exemplo só \"uma pizza\"), "
            "escreva o que ele disse, sem escolher por ele. Em uma troca, retire o item "
            "substituído antes de acrescentar o novo; não acrescente produtos de exemplos.",
            '- "endereco": só se o cliente falou um endereço de entrega diferente; senão null.',
            '- "fechar": true só quando o cliente disser que terminou o pedido (por exemplo '
            '"é só isso", "pode fechar"); senão false.',
            "Use apenas os produtos e preços do cardápio. Nunca invente produto ou preço.",
            "Nunca arredonde quantidades fracionadas: preserve a fração para o código pedir "
            "esclarecimento. Mantenha separadas unidades com observações diferentes. "
            "Se houver dúvida pendente, peça esclarecimento; não considere um simples sim "
            "como solução. Não invente taxa, prazo ou desconto.",
            "",
            "Pedido atual:",
            atual,
            "Pendência: {}".format(self._pendencia or "nenhuma"),
            "Pagamento: {}".format(PAGAMENTO_FALADO.get(self.pagamento, "ainda não informado")),
            "Endereço de entrega: {}".format(
                self.endereco_entrega or self.endereco_do_cadastro or "ainda não informado"),
            "",
            "Cardápio:",
            _cardapio_em_texto(cardapio),
        ])

    # --- quem nao quis conta so conversa com o llama, sem pedido ---

    def _conversar_com_llm(self, texto):
        db = self._sessao()
        try:
            cardapio = _cardapio_em_texto(repositorio.listar_cardapio(db))
        except SQLAlchemyError as erro:
            print(f"[atendimento] erro ao ler o cardapio: {erro}")
            cardapio = "(cardápio indisponível agora: não informe preços)"
        finally:
            db.close()

        sistema = "\n".join([
            _prompt_base(),
            "Você é o atendente de telefone de uma pizzaria. Fale em português do Brasil.",
            "Sua resposta será lida em voz alta: use no máximo duas frases curtas, "
            "sem listas, sem emojis e sem markdown.",
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
