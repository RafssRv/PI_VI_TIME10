-- leva um banco que ja existia (criado antes dos tamanhos de pizza) para o esquema atual,
-- sem apagar clientes nem pedidos. quem sobe o banco do zero nao precisa disso: o banco.sql
-- ja vem com tudo. pode rodar mais de uma vez, nao duplica nada.
--
--   docker exec -i pizzaria-db psql -U pizzaria -d pizzaria < database/migracao_tamanhos.sql
--   python backend/seed.py --completar     # poe os tamanhos e os produtos novos do cardapio

CREATE TABLE IF NOT EXISTS tamanho (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(10) NOT NULL UNIQUE,
    fatias INTEGER NOT NULL CHECK (fatias > 0),
    desconto NUMERIC(10,2) NOT NULL DEFAULT 0 CHECK (desconto >= 0)
);

-- pizza pedida antes disso fica com tamanho null: o historico antigo nao sabia o tamanho
ALTER TABLE item_pedido ADD COLUMN IF NOT EXISTS tamanho_id INTEGER REFERENCES tamanho(id);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'item_pedido_preco_unitario_check') THEN
        ALTER TABLE item_pedido ADD CONSTRAINT item_pedido_preco_unitario_check CHECK (preco_unitario > 0);
    END IF;
END $$;

-- tamanhos de refrigerante (lata, 600 ml, 2 litros): o tamanho ganha um grupo e o produto diz
-- qual grupo vale pra ele
ALTER TABLE tamanho ADD COLUMN IF NOT EXISTS grupo VARCHAR(20) NOT NULL DEFAULT 'pizza';
ALTER TABLE tamanho ALTER COLUMN fatias DROP NOT NULL;
ALTER TABLE tamanho DROP CONSTRAINT IF EXISTS tamanho_nome_key;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tamanho_grupo_nome_key') THEN
        ALTER TABLE tamanho ADD CONSTRAINT tamanho_grupo_nome_key UNIQUE (grupo, nome);
    END IF;
END $$;
ALTER TABLE produto ADD COLUMN IF NOT EXISTS grupo_tamanho VARCHAR(20);

-- o refrigerante deixa de ter o volume no nome: "Coca-Cola 2 Litros" vira "Coca-Cola" com tamanhos.
-- os pedidos antigos continuam apontando pro mesmo produto
UPDATE produto SET nome = 'Coca-Cola', descricao = 'refrigerante gelado'
    WHERE nome = 'Coca-Cola 2 Litros' AND NOT EXISTS (SELECT 1 FROM produto WHERE nome = 'Coca-Cola');
UPDATE produto SET nome = 'Guaraná', descricao = 'refrigerante gelado'
    WHERE nome = 'Guaraná 2 Litros' AND NOT EXISTS (SELECT 1 FROM produto WHERE nome = 'Guaraná');
UPDATE produto SET nome = 'Fanta Laranja', descricao = 'refrigerante gelado'
    WHERE nome = 'Fanta Laranja 2 Litros' AND NOT EXISTS (SELECT 1 FROM produto WHERE nome = 'Fanta Laranja');
UPDATE produto SET nome = 'Sprite', descricao = 'refrigerante gelado'
    WHERE nome = 'Sprite 2 Litros' AND NOT EXISTS (SELECT 1 FROM produto WHERE nome = 'Sprite');
