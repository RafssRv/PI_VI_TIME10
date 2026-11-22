-- esquema do banco da pizzaria (postgres 16).
-- o docker-compose monta esse arquivo em /docker-entrypoint-initdb.d, entao ele so roda
-- quando o volume do banco ta vazio. se mexer aqui, tem q rodar "docker compose down -v"
-- e subir de novo, senao o postgres ignora e o banco continua com o esquema velho.

CREATE TABLE cliente (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    -- cpf nunca entra em texto puro, o python guarda o hmac-sha256 (64 chars de hex)
    cpf_hash VARCHAR(64) NOT NULL UNIQUE,
    telefone VARCHAR(20),
    endereco TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE produto (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    descricao TEXT,
    categoria VARCHAR(30) NOT NULL,
    preco NUMERIC(10,2) NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT true,
    -- qual tabela de tamanhos vale pro produto: 'pizza', 'refrigerante' ou null (tamanho unico)
    grupo_tamanho VARCHAR(20)
);

-- tamanhos de pizza (pequena, media, grande) e de refrigerante (lata, 600 ml, 2 litros).
-- o preco do cardapio eh o do maior tamanho e o desconto sai dele, assim reajustar o
-- cardapio reajusta todos os tamanhos de uma vez
CREATE TABLE tamanho (
    id SERIAL PRIMARY KEY,
    grupo VARCHAR(20) NOT NULL DEFAULT 'pizza',
    nome VARCHAR(10) NOT NULL,
    -- so pizza tem fatias; refrigerante fica com null
    fatias INTEGER CHECK (fatias > 0),
    desconto NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (desconto >= 0),
    UNIQUE (grupo, nome)
);

CREATE TABLE pedido (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES cliente(id),
    endereco_entrega TEXT,
    forma_pagamento VARCHAR(20),
    -- "troco pra 100": nota com que o cliente vai pagar em dinheiro. vazio quando nao precisa de troco
    troco_para NUMERIC(10,2) CHECK (troco_para > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'aberto',
    total NUMERIC(10,2) NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE item_pedido (
    id SERIAL PRIMARY KEY,
    -- apagou o pedido, some com os itens junto
    pedido_id INTEGER NOT NULL REFERENCES pedido(id) ON DELETE CASCADE,
    produto_id INTEGER NOT NULL REFERENCES produto(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    -- guarda o preco do momento da venda, pq o cardapio pode mudar depois
    preco_unitario NUMERIC(10,2) NOT NULL CHECK (preco_unitario > 0),
    observacao TEXT,
    -- so pizza e refrigerante tem tamanho: agua, suco, sobremesa e borda ficam com null
    tamanho_id INTEGER REFERENCES tamanho(id)
);

-- historico do cliente (rf05/rf08) busca sempre por cliente_id
CREATE INDEX idx_pedido_cliente ON pedido (cliente_id);

-- e pra montar/ler o pedido a gnt puxa os itens pelo pedido_id
CREATE INDEX idx_item_pedido_pedido ON item_pedido (pedido_id);
