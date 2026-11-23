-- leva um banco que ja existia para as regras de integridade do esquema atual, sem apagar nada.
-- quem sobe o banco do zero nao precisa disso: o banco.sql ja vem com tudo.
-- pode rodar mais de uma vez. se alguma linha antiga quebrar uma regra, o postgres para e
-- diz qual constraint falhou: corrija a linha e rode de novo.
--
--   docker exec -i pizzaria-db psql -U pizzaria -d pizzaria < database/migracao_integridade.sql

DO $$
DECLARE
    regra RECORD;
BEGIN
    FOR regra IN
        SELECT * FROM (VALUES
            ('produto', 'produto_preco_positivo', 'CHECK (preco > 0)'),
            ('produto', 'produto_grupo_valido', 'CHECK (grupo_tamanho IN (''pizza'', ''refrigerante''))'),
            ('tamanho', 'tamanho_grupo_valido', 'CHECK (grupo IN (''pizza'', ''refrigerante''))'),
            ('pedido', 'pedido_forma_pagamento_valida',
             'CHECK (forma_pagamento IN (''pix'', ''dinheiro'', ''cartao_credito'', ''cartao_debito''))'),
            ('pedido', 'pedido_total_nao_negativo', 'CHECK (total >= 0)'),
            ('pedido', 'pedido_troco_so_em_dinheiro', 'CHECK (troco_para IS NULL OR (forma_pagamento IS NOT NULL AND forma_pagamento = ''dinheiro''))')
        ) AS r (tabela, nome, definicao)
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = regra.nome) THEN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', regra.tabela, regra.nome, regra.definicao);
        END IF;
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_pedido_criado_em ON pedido (criado_em);
