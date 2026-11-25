from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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
    __table_args__ = (
        CheckConstraint("preco > 0", name="produto_preco_positivo"),
        CheckConstraint("grupo_tamanho IN ('pizza', 'refrigerante')", name="produto_grupo_valido"),
    )

    id = Column(Integer, primary_key=True)
    nome = Column(String(100), nullable=False)
    descricao = Column(Text)
    categoria = Column(String(30), nullable=False)
    preco = Column(Numeric(10, 2), nullable=False)
    # produto fora do cardapio a gente desativa em vez de apagar, senao quebra os pedidos antigos
    ativo = Column(Boolean, nullable=False, server_default="true")
    # qual tabela de tamanhos vale: "pizza", "refrigerante" ou None (tamanho unico)
    grupo_tamanho = Column(String(20))

    def __repr__(self):
        return "<Produto id={} nome={!r} preco={}>".format(self.id, self.nome, self.preco)


class Tamanho(Base):
    __tablename__ = "tamanho"
    __table_args__ = (
        CheckConstraint("fatias > 0", name="ck_tamanho_fatias_positivas"),
        CheckConstraint("desconto >= 0", name="ck_tamanho_desconto_nao_negativo"),
        CheckConstraint("grupo IN ('pizza', 'refrigerante')", name="tamanho_grupo_valido"),
        UniqueConstraint("grupo", "nome", name="tamanho_grupo_nome_key"),
    )

    id = Column(Integer, primary_key=True)
    # "pizza" ou "refrigerante": o produto diz qual grupo vale pra ele
    grupo = Column(String(20), nullable=False, server_default="pizza")
    nome = Column(String(10), nullable=False)
    # so pizza tem fatias
    fatias = Column(Integer)
    # quanto sai do preco do cardapio, q eh o do maior tamanho
    desconto = Column(Numeric(10, 2), nullable=False, server_default="0")

    def __repr__(self):
        return "<Tamanho id={} nome={!r} desconto={}>".format(self.id, self.nome, self.desconto)


# andamento do pedido: o atendente grava "aberto", o painel avanca um passo por vez
STATUS_DO_PEDIDO = ("aberto", "em_preparo", "saiu_entrega", "entregue", "cancelado")


class Pedido(Base):
    __tablename__ = "pedido"
    __table_args__ = (
        CheckConstraint("status IN ({})".format(", ".join("'{}'".format(s) for s in STATUS_DO_PEDIDO)),
                        name="pedido_status_valido"),
        CheckConstraint("troco_para > 0", name="ck_pedido_troco_positivo"),
        CheckConstraint("forma_pagamento IN ('pix', 'dinheiro', 'cartao_credito', 'cartao_debito')",
                        name="pedido_forma_pagamento_valida"),
        CheckConstraint("troco_para IS NULL OR (forma_pagamento IS NOT NULL AND forma_pagamento = 'dinheiro')", name="pedido_troco_so_em_dinheiro"),
        CheckConstraint("total >= 0", name="pedido_total_nao_negativo"),
        Index("idx_pedido_criado_em", "criado_em"),
    )

    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("cliente.id"), nullable=False)
    endereco_entrega = Column(Text)
    forma_pagamento = Column(String(20))
    # nota com que o cliente paga em dinheiro ("troco pra 100"); None quando nao precisa de troco
    troco_para = Column(Numeric(10, 2))
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
        CheckConstraint("preco_unitario > 0", name="ck_item_pedido_preco_positivo"),
    )

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedido.id", ondelete="CASCADE"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produto.id"), nullable=False)
    quantidade = Column(Integer, nullable=False)
    # copia do preco na hora da compra, pq se o cardapio mudar o pedido antigo nao pode mudar junto
    preco_unitario = Column(Numeric(10, 2), nullable=False)
    observacao = Column(Text)
    # so pizza tem tamanho, o resto fica null
    tamanho_id = Column(Integer, ForeignKey("tamanho.id"))

    pedido = relationship("Pedido", back_populates="itens")
    produto = relationship("Produto")
    tamanho = relationship("Tamanho")

    def __repr__(self):
        return "<ItemPedido id={} pedido_id={} produto_id={} qtd={}>".format(
            self.id, self.pedido_id, self.produto_id, self.quantidade
        )
