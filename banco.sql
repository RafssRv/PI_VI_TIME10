CREATE TABLE cliente (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(100) NOT NULL,
    cpf_hash  VARCHAR(64) NOT NULL UNIQUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE produto (
    id        SERIAL PRIMARY KEY,
    nome      VARCHAR(100) NOT NULL,
    descricao TEXT,
    categoria VARCHAR(30) NOT NULL,
    preco     NUMERIC(10,2) NOT NULL,
    ativo     BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE pedido (
    id               SERIAL PRIMARY KEY,
    cliente_id       INTEGER NOT NULL REFERENCES cliente (id),
    endereco_entrega TEXT,
    forma_pagamento  VARCHAR(20),
    status           VARCHAR(20) NOT NULL DEFAULT 'aberto',
    total            NUMERIC(10,2) NOT NULL DEFAULT 0,
    criado_em        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE item_pedido (
    id             SERIAL PRIMARY KEY,
    pedido_id      INTEGER NOT NULL REFERENCES pedido (id) ON DELETE CASCADE,
    produto_id     INTEGER NOT NULL REFERENCES produto (id),
    quantidade     INTEGER NOT NULL CHECK (quantidade > 0),
    preco_unitario NUMERIC(10,2) NOT NULL
);