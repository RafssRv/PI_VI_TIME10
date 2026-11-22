-- leva um banco que ja existia para o esquema com troco, sem apagar clientes nem pedidos.
-- quem sobe o banco do zero nao precisa disso: o banco.sql ja vem com a coluna.
-- pode rodar mais de uma vez, nao duplica nada.
--
--   docker exec -i pizzaria-db psql -U pizzaria -d pizzaria < database/migracao_troco.sql

ALTER TABLE pedido ADD COLUMN IF NOT EXISTS troco_para NUMERIC(10,2) CHECK (troco_para > 0);
