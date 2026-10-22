"""Rascunho de uma conversa: itens e confirmação, sem gravação no banco.

O chamador fornece o cardápio confiável e operações já esclarecidas. Este módulo
não interpreta linguagem natural nem aceita preços gerados pelo modelo.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable, Iterable, TypeVar
from uuid import uuid4


class ErroPedido(ValueError):
    """Operação que precisa ser corrigida ou esclarecida com o cliente."""


@dataclass(frozen=True)
class ProdutoCardapio:
    id: int
    nome: str
    preco: Decimal
    ativo: bool = True


@dataclass(frozen=True)
class ItemResumo:
    id: str
    produto_id: int
    nome: str
    quantidade: int
    preco_unitario: Decimal
    observacao: str = ""

    @property
    def subtotal(self) -> Decimal:
        return self.preco_unitario * self.quantidade


def _reais(valor: Decimal) -> str:
    return f"R$ {valor:.2f}".replace(".", ",")


@dataclass(frozen=True)
class ResumoPedido:
    token: str
    itens: tuple[ItemResumo, ...]

    @property
    def subtotal(self) -> Decimal:
        return sum((item.subtotal for item in self.itens), Decimal("0.00"))

    @property
    def texto(self) -> str:
        partes = []
        for item in self.itens:
            observacao = f" (solicitação: {item.observacao})" if item.observacao else ""
            partes.append(
                f"{item.quantidade} de {item.nome}{observacao}, "
                f"{_reais(item.preco_unitario)} por unidade, {_reais(item.subtotal)}"
            )
        return (
            f"Resumo: {'; '.join(partes)}. "
            f"Subtotal dos produtos: {_reais(self.subtotal)}. Confirma esse resumo?"
        )


T = TypeVar("T")


class ControlePedido:
    """Crie uma instância por conversa; não compartilhe entre atendimentos.

    `resumir()` produz o texto e o token a guardar no servidor. A confirmação
    precisa desse token, referente ao resumo efetivamente apresentado ao cliente.
    Alterações e dúvidas invalidam a confirmação. Nada aqui registra uma compra.
    """

    def __init__(self, cardapio: Iterable[ProdutoCardapio]):
        self._cardapio = {}
        for produto in cardapio:
            if type(produto.id) is not int or produto.id <= 0:
                raise ErroPedido("O identificador do produto deve ser inteiro positivo.")
            if produto.id in self._cardapio:
                raise ErroPedido("Há identificadores duplicados no cardápio.")
            if not isinstance(produto.nome, str) or not produto.nome.strip():
                raise ErroPedido("O produto precisa de um nome.")
            preco = produto.preco
            if (
                not isinstance(preco, Decimal)
                or not preco.is_finite()
                or preco < 0
                or preco.as_tuple().exponent < -2
            ):
                raise ErroPedido("O preço deve ser Decimal não negativo com até dois decimais.")
            if type(produto.ativo) is not bool:
                raise ErroPedido("A disponibilidade deve ser verdadeira ou falsa.")
            self._cardapio[produto.id] = produto
        self._itens: dict[str, ItemResumo] = {}
        self._resumo: ResumoPedido | None = None
        self._confirmado = False
        self._pendencia: str | None = None

    @property
    def itens(self) -> tuple[ItemResumo, ...]:
        return tuple(self._itens.values())

    @property
    def confirmado(self) -> bool:
        return self._confirmado

    @property
    def pendencia(self) -> str | None:
        return self._pendencia

    def _invalidar(self) -> None:
        self._resumo = None
        self._confirmado = False

    def definir_pendencia(self, pergunta: str | None) -> None:
        """Registre uma dúvida; use None somente depois de esclarecê-la."""
        if pergunta is not None and (not isinstance(pergunta, str) or not pergunta.strip()):
            raise ErroPedido("A pendência precisa de uma pergunta não vazia.")
        self._pendencia = pergunta.strip() if pergunta is not None else None
        self._invalidar()

    @staticmethod
    def _quantidade(quantidade: int) -> None:
        if type(quantidade) is not int or quantidade <= 0:
            raise ErroPedido("Informe uma quantidade inteira maior que zero.")

    @staticmethod
    def _observacao(observacao: str) -> str:
        if not isinstance(observacao, str):
            raise ErroPedido("A observação deve ser um texto.")
        return observacao.strip()

    def _produto(self, produto_id: int) -> ProdutoCardapio:
        if type(produto_id) is not int or produto_id not in self._cardapio:
            raise ErroPedido("O produto não consta no cardápio fornecido.")
        produto = self._cardapio[produto_id]
        if not produto.ativo:
            raise ErroPedido("O produto não está disponível no cardápio.")
        return produto

    @staticmethod
    def _item(itens: dict[str, ItemResumo], item_id: str) -> ItemResumo:
        if not isinstance(item_id, str) or item_id not in itens:
            raise ErroPedido("O item não consta neste resumo.")
        return itens[item_id]

    def _editar(self, operacao: Callable[[dict[str, ItemResumo]], T]) -> T:
        # A cópia impede que uma troca inválida remova apenas metade do pedido.
        novos = dict(self._itens)
        try:
            resultado = operacao(novos)
        except ErroPedido as erro:
            self.definir_pendencia(str(erro))
            raise
        self._itens = novos
        self._invalidar()
        # Uma operação válida não resolve automaticamente outra dúvida pendente.
        return resultado

    def _incluir(self, itens, produto_id, quantidade, observacao) -> str:
        produto = self._produto(produto_id)
        self._quantidade(quantidade)
        observacao = self._observacao(observacao)
        for item in itens.values():
            if item.produto_id == produto_id and item.observacao == observacao:
                itens[item.id] = replace(item, quantidade=item.quantidade + quantidade)
                return item.id
        item_id = uuid4().hex
        itens[item_id] = ItemResumo(
            item_id, produto.id, produto.nome, quantidade, produto.preco, observacao
        )
        return item_id

    def adicionar(self, produto_id: int, quantidade: int, observacao: str = "") -> str:
        return self._editar(lambda itens: self._incluir(itens, produto_id, quantidade, observacao))

    def definir_quantidade(self, item_id: str, quantidade: int) -> None:
        def alterar(itens):
            item = self._item(itens, item_id)
            self._quantidade(quantidade)
            itens[item_id] = replace(item, quantidade=quantidade)
        self._editar(alterar)

    def alterar_observacao(self, item_id: str, observacao: str) -> None:
        def alterar(itens):
            item = self._item(itens, item_id)
            itens[item_id] = replace(item, observacao=self._observacao(observacao))
        self._editar(alterar)

    def _retirar(self, itens, item_id, quantidade) -> None:
        item = self._item(itens, item_id)
        self._quantidade(quantidade)
        if quantidade > item.quantidade:
            raise ErroPedido("A quantidade a retirar excede a quantidade do item.")
        restante = item.quantidade - quantidade
        if restante:
            itens[item_id] = replace(item, quantidade=restante)
        else:
            del itens[item_id]

    def remover(self, item_id: str, quantidade: int) -> None:
        self._editar(lambda itens: self._retirar(itens, item_id, quantidade))

    def substituir(
        self, item_id: str, quantidade_retirar: int, produto_id: int,
        quantidade_adicionar: int, observacao: str = "",
    ) -> str:
        """Troca quantidades explícitas; não transfere observações ao novo produto."""
        def trocar(itens):
            self._retirar(itens, item_id, quantidade_retirar)
            return self._incluir(itens, produto_id, quantidade_adicionar, observacao)
        return self._editar(trocar)

    def limpar(self) -> str:
        self._itens.clear()
        self._pendencia = None
        self._invalidar()
        return "Retirei os itens do resumo. Nenhum pedido foi registrado."

    def resumir(self) -> ResumoPedido:
        if self._pendencia:
            raise ErroPedido(f"Esclareça antes de confirmar: {self._pendencia}")
        if not self._itens:
            raise ErroPedido("Não há itens para confirmar.")
        if self._resumo is None:
            self._resumo = ResumoPedido(uuid4().hex, self.itens)
        return self._resumo

    def confirmar(self, token: str) -> str:
        if self._pendencia or self._resumo is None or token != self._resumo.token:
            raise ErroPedido("Apresente o resumo atual e peça nova confirmação.")
        self._confirmado = True
        return (
            "Resumo confirmado por você. O pedido ainda não foi registrado; "
            "a pizzaria precisa concluir o atendimento."
        )
