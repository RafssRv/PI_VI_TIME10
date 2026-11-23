-- leva um banco que ja existia para o esquema com o andamento do pedido, sem apagar nada.
-- quem sobe o banco do zero nao precisa disso: o banco.sql ja vem com tudo.
-- pode rodar mais de uma vez, nao duplica nada.
--
--   docker exec -i pizzaria-db psql -U pizzaria -d pizzaria < database/migracao_status.sql

-- o seed antigo gravava "concluido" e o atendente sempre gravou "aberto". antes do CHECK:
-- concluido vira entregue, e o "aberto" com mais de 12 horas ja saiu faz tempo (ninguem marcava)
UPDATE pedido SET status = 'entregue' WHERE status IN ('concluido', 'recebido');
UPDATE pedido SET status = 'entregue' WHERE status = 'aberto' AND criado_em < now() - interval '12 hours';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pedido_status_valido') THEN
        ALTER TABLE pedido ADD CONSTRAINT pedido_status_valido
            CHECK (status IN ('aberto', 'em_preparo', 'saiu_entrega', 'entregue', 'cancelado'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_pedido_em_andamento ON pedido (criado_em)
    WHERE status IN ('aberto', 'em_preparo', 'saiu_entrega');
