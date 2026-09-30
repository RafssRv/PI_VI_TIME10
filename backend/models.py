from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database import Base

# dinheiro sempre Numeric(10, 2), nunca Float, se nao 19.90 vira 19.899999999


class Cliente(Base):
    __tablename__ = "cliente"

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    # o cpf nunca entra aqui em texto puro (RNF06), so o hmac-sha256 dele, q da 64 chars
    cpf_hash = Column(String(64), nullable=False, unique=True)
    telefone = Column(String(20))
    endereco = Column(Text)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    pedidos = relationship("Pedido", back_populates="cliente")

    def __repr__(self):
        return "<Cliente id={} nome={!r}>".format(self.id, self.nome)


class Produto(Base):
    __tablename__ = "produto"

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    descricao = Column(Text)
    categoria = Column(String(30), nullable=False)
    preco = Column(Numeric(10, 2), nullable=False)
    # produto fora do cardapio a gente desativa em vez de apagar, senao quebra os pedidos antigos
    ativo = Column(Boolean, nullable=False, server_default="true")

    def __repr__(self):
        return "<Produto id={} nome={!r} preco={}>".format(self.id, self.nome, self.preco)


class Pedido(Base):
    __tablename__ = "pedido"

    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("cliente.id"), nullable=False)
    endereco_entrega = Column(Text)
    forma_pagamento = Column(String(20))
    status = Column(String(20), nullable=False, server_default="aberto")
    total = Column(Numeric(10, 2), nullable=False, server_default="0")
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    cliente = relationship("Cliente", back_populates="pedidos")
    # delete-orphan: tirou o item da lista, ele some do banco junto
    itens = relationship("ItemPedido", back_populates="pedido", cascade="all, delete-orphan")

    def __repr__(self):
        return "<Pedido id={} cliente_id={} status={!r} total={}>".format(
            self.id, self.cliente_id, self.status, self.total
        )


class ItemPedido(Base):
    __tablename__ = "item_pedido"
    __table_args__ = (
        CheckConstraint("quantidade > 0", name="ck_item_pedido_quantidade_positiva"),
    )

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedido.id", ondelete="CASCADE"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produto.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    # copia do preco na hora da compra, pq se o cardapio mudar o pedido antigo nao pode mudar junto
    preco_unitario = Column(Numeric(10, 2), nullable=False)
    observacao = Column(Text)

    pedido = relationship("Pedido", back_populates="itens")
    produto = relationship("Produto")

    def __repr__(self):
        return "<ItemPedido id={} pedido_id={} produto_id={} qtd={}>".format(
            self.id, self.pedido_id, self.produto_id, self.quantidade
        )
