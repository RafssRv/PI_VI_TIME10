# DAD-01 Modelo de dados

Status: Pronto e testado contra o Postgres — esquema (`banco.sql`), models do SQLAlchemy, repositório e seed com cardápio, 6 clientes e 30 pedidos históricos; nenhuma rota do `backend/main.py` chama o repositório ainda, o consumo vai acontecer quando a orquestração existir.
Backlog: doc/backlog.md (DAD-01). Requisitos: RF03, RF04, RF05, RF07, RF08, RF09, RF11, RNF06, RIA04.

## Objetivo

O atendente precisa de memória: saber quem é o cliente que ligou, o que ele já pediu antes, o que a casa vende e por quanto, e guardar o pedido fechado. Este item define as quatro tabelas que sustentam isso, os tipos exatos de cada coluna e a única camada de código autorizada a falar com o banco. Sem ele, cada parte do pipeline de voz inventaria sua própria query e o CPF acabaria em texto puro em algum `SELECT`.

## Usuários e papéis

Item interno. Nenhum usuário final toca nele diretamente: quem usa é o restante do backend (orquestração, WebSocket e as rotas), e o time durante o desenvolvimento, pelo seed.

## Pontos de entrada

- `banco.sql` — esquema. O `docker-compose.yml` monta o arquivo em `/docker-entrypoint-initdb.d/banco.sql:ro`, então o Postgres o executa sozinho, mas **só no primeiro boot com o volume `pgdata` vazio**.
- `backend/config.py` — `URL_DO_BANCO`, lida de `DATABASE_URL`, com default `postgresql+psycopg://pizzaria:pizzaria123@localhost:5432/pizzaria` (bate com o `docker-compose.yml`).
- `backend/database.py` — `engine`, `SessionLocal`, `Base` e a dependência `get_db()`, que abre a sessão e garante o `close()` no `finally`.
- `backend/models.py` — as classes `Cliente`, `Produto`, `Pedido` e `ItemPedido`.
- `backend/repositorio.py` — as funções públicas listadas no Escopo.
- `backend/seed.py` — popula o banco de desenvolvimento.

```bash
npm run banco          # sobe o postgres no docker
npm run banco:recriar  # docker compose down -v && up -d: apaga o volume e reaplica o banco.sql
npm run seed           # python backend/seed.py
npm run seed:recriar   # python backend/seed.py --recriar: limpa as tabelas antes de popular
```

## Telas

Nenhuma. Item de infraestrutura.

## Escopo

### Entidades (pronto)

Quatro tabelas. Os tipos abaixo são os do `banco.sql`; `backend/models.py` declara os mesmos.

**cliente** — quem faz o pedido (RF03, RF04).

| Coluna | Tipo | Obrigatório | Para que serve |
| --- | --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | sim | Chave interna, usada pelo `pedido.cliente_id`. |
| `nome` | `VARCHAR(100)` | sim | Como o atendente chama o cliente. |
| `cpf_hash` | `VARCHAR(64) UNIQUE` | sim | HMAC-SHA256 do CPF em hexadecimal. É por ele que o cliente é localizado. Detalhe do hash: CLI-01. |
| `telefone` | `VARCHAR(20)` | não | Contato. Gravado só com dígitos. |
| `endereco` | `TEXT` | não | Endereço padrão; vira o `endereco_entrega` do pedido quando nenhum outro é informado. |
| `criado_em` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | sim | Data de cadastro. |

**produto** — o cardápio (RF07, RIA04).

| Coluna | Tipo | Obrigatório | Para que serve |
| --- | --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | sim | Chave interna, referenciada por `item_pedido.produto_id`. |
| `nome` | `VARCHAR(100)` | sim | Nome do produto; é contra ele que o texto transcrito é comparado. |
| `descricao` | `TEXT` | não | Ingredientes, para responder dúvida do cliente. |
| `categoria` | `VARCHAR(30)` | sim | Agrupa o cardápio. O seed usa `pizza salgada`, `pizza doce`, `bebida`, `sobremesa` e `borda`. |
| `preco` | `NUMERIC(10,2)` | sim | Preço atual, o que vale para quem está pedindo agora. |
| `ativo` | `BOOLEAN NOT NULL DEFAULT true` | sim | Produto fora do cardápio é desativado, nunca apagado, senão os pedidos antigos quebram. |

**pedido** — o cabeçalho do pedido (RF09, RF11).

| Coluna | Tipo | Obrigatório | Para que serve |
| --- | --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | sim | Chave interna. |
| `cliente_id` | `INTEGER NOT NULL REFERENCES cliente(id)` | sim | De quem é o pedido. Sem cascade: cliente com pedido não se apaga. |
| `endereco_entrega` | `TEXT` | não | Endereço desta entrega; pode diferir do cadastro. |
| `forma_pagamento` | `VARCHAR(20)` | não | Uma das quatro formas aceitas, ou nulo enquanto o cliente não decidiu. |
| `status` | `VARCHAR(20) NOT NULL DEFAULT 'aberto'` | sim | Estado do pedido. O seed grava `concluido` no histórico; ver Questões em aberto. |
| `total` | `NUMERIC(10,2) NOT NULL DEFAULT 0` | sim | Soma calculada no `salvar_pedido`, não recalculada na leitura. |
| `criado_em` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | sim | Momento do pedido; é a ordenação do histórico. |

**item_pedido** — uma linha por produto dentro do pedido (RF09, RIA04).

| Coluna | Tipo | Obrigatório | Para que serve |
| --- | --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | sim | Chave interna. |
| `pedido_id` | `INTEGER NOT NULL REFERENCES pedido(id) ON DELETE CASCADE` | sim | A que pedido a linha pertence. |
| `produto_id` | `INTEGER NOT NULL REFERENCES produto(id)` | sim | Que produto foi vendido. Sem cascade: produto vendido não se apaga. |
| `quantidade` | `INTEGER NOT NULL CHECK (quantidade > 0)` | sim | Quantas unidades. |
| `preco_unitario` | `NUMERIC(10,2)` | sim | Preço no momento da venda, cópia do `produto.preco`. |
| `observacao` | `TEXT` | não | "sem cebola", "massa fina" — o que o cliente pediu para aquela linha. |

### Relacionamentos e por que `item_pedido` existe (pronto)

```
cliente 1 --< N pedido 1 --< N item_pedido >-- N 1 produto
```

Um cliente tem muitos pedidos. Um pedido tem muitos itens. Um produto aparece em muitos itens.

`item_pedido` é a tabela associativa entre `pedido` e `produto`, e existe porque a relação entre os dois é N para N: um pedido leva vários produtos e um produto vai em vários pedidos. Sem ela só haveria duas saídas ruins — repetir colunas `produto_1`, `produto_2`… no `pedido`, com limite arbitrário, ou gravar os itens em texto, o que impede qualquer consulta. Além disso a associação carrega dados próprios, que não são nem do pedido nem do produto: `quantidade`, `preco_unitario` e `observacao`. São eles que sustentam o RF05 e o RF08 — `itens_mais_pedidos_do_cliente` só consegue somar o que o cliente mais pediu porque existe uma linha por produto com a quantidade ao lado.

No SQLAlchemy os dois lados estão declarados: `Pedido.itens` com `cascade="all, delete-orphan"` e `back_populates`, mais `ItemPedido.produto` e `Cliente.pedidos`.

### Decisões técnicas (pronto)

**`preco_unitario` copiado no momento da venda.** O item não aponta para o preço de hoje; ele guarda o preço que o cliente pagou. Se a pizza subir de R$ 59,90 para R$ 64,90 amanhã, o pedido da semana passada continua valendo R$ 59,90 e o `total` continua batendo com a soma dos itens. Sem a cópia, todo o histórico se reescreveria sozinho a cada reajuste — e o histórico é justamente a base do RF05 e do RF08.

**`NUMERIC(10,2)` em vez de `float`.** Ponto flutuante binário não representa `19.90` exatamente; somar dez itens em `float` produz centavos de erro e valores como `19.899999999`. `NUMERIC` é decimal exato. No Python o par disso é o `Decimal`: o `salvar_pedido` acumula em `Decimal("0.00")`, converte o preço com `Decimal(str(produto.preco))` — `str` antes, porque `Decimal` de um `float` já nasce com dízima — e fecha com `total.quantize(Decimal("0.01"))`. O seed também cria os preços a partir de string, pelo mesmo motivo.

**Dois índices, e só esses dois.** `idx_pedido_cliente` em `pedido (cliente_id)`, porque toda consulta de histórico (RF05, RF08) filtra por cliente; `idx_item_pedido_pedido` em `item_pedido (pedido_id)`, porque ler ou montar um pedido sempre puxa os itens por ele. As demais buscas caem em chave primária ou varrem o cardápio inteiro, que tem poucas dezenas de linhas — índice ali seria peso sem ganho.

**`ON DELETE CASCADE` no `item_pedido`.** Item de pedido não existe sozinho: apagou o pedido, os itens vão junto, no banco. No ORM o espelho disso é o `cascade="all, delete-orphan"` em `Pedido.itens`, que remove do banco o item tirado da lista em memória. As outras duas chaves estrangeiras (`pedido.cliente_id` e `item_pedido.produto_id`) são deliberadamente sem cascade: apagar um cliente ou um produto que já vendeu levaria histórico junto, e é por isso que produto sai do cardápio por `ativo = false`.

### Interface do repositório (pronto)

`backend/repositorio.py` é a única porta de entrada para o banco. Toda função recebe a `Session` (`db`) pronta de fora; quem abre e fecha é o `get_db()` do `database.py`.

| Função | Recebe | Devolve | Requisito |
| --- | --- | --- | --- |
| `buscar_cliente_por_cpf(db, cpf)` | CPF como o cliente falou | `Cliente` ou `None` | RF03 |
| `criar_cliente(db, nome, cpf, telefone=None, endereco=None)` | Dados do cadastro | `Cliente` já com `id` | RF04 |
| `listar_cardapio(db, categoria=None, apenas_ativos=True)` | Categoria opcional, como falada | Lista de `Produto`, ordenada por categoria e nome | RF07 |
| `buscar_produtos(db, nome)` | Pedaço de nome vindo da transcrição | Lista de `Produto` ativos que casam (vazia se nenhum) | RF07, RIA04 |
| `buscar_produto(db, nome)` | Pedaço de nome | O `Produto` só quando há um único candidato; `None` com zero ou mais de um | RF07, RIA04 |
| `historico_cliente(db, cliente_id, limite=5)` | Id do cliente | Últimos pedidos, do mais novo ao mais antigo, com itens e produtos já carregados | RF05 |
| `itens_mais_pedidos_do_cliente(db, cliente_id, limite=3)` | Id do cliente | Lista de `(Produto, quantidade_somada)`, da maior para a menor | RF08 |
| `itens_mais_pedidos_da_casa(db, limite=3)` | Só a sessão | Lista de `(Produto, quantidade_somada)` | RF08 |
| `salvar_pedido(db, cliente_id, itens, endereco_entrega=None, forma_pagamento=None)` | Lista de dicionários com as chaves `produto`, `quantidade` (default 1) e `observacao` | `Pedido` gravado, com `total` e itens | RF09, RF11, RIA04 |
| `interpretar_pagamento(forma_pagamento)` | A forma como o cliente falou | String canônica de `FORMAS_PAGAMENTO`; `ValueError` na dúvida | RF09 |

Todas as funções acima citam o requisito na própria docstring, menos `interpretar_pagamento`: ali a associação com o RF09 é deste documento, o código não cita requisito.

Duas notas sobre a busca de produto. Primeira: a comparação é feita em texto normalizado dos dois lados pelo `_normalizar` — sem acento, minúsculo, pontuação virando espaço — porque a transcrição de voz não devolve acento nem hífen; é assim que "coca cola" acha "Coca-Cola 2 Litros". Segunda: `buscar_produtos` devolve lista e `buscar_produto` devolve `None` no empate de propósito. Desempatar no código é gravar pedido errado calado; quem precisa perguntar ao cliente usa a lista.

`FORMAS_PAGAMENTO` é a tupla `("pix", "dinheiro", "cartao_credito", "cartao_debito")`. O `interpretar_pagamento` traduz a fala para ela por sinais (`credito` para `cartao_credito`, `especie` e `vivo` para `dinheiro`) e recusa o que for ambíguo: "cartao" e "maquininha" sozinhos não dizem crédito ou débito, então levanta `ValueError` pedindo a pergunta.

## Dados

Lê e escreve as quatro tabelas, sempre via `repositorio.py`:

| Operação | Tabela e colunas |
| --- | --- |
| Lê | `cliente` (todas, filtrando por `cpf_hash`); `produto` (todas, filtrando por `ativo`, `nome` e `categoria`); `pedido` (todas, filtrando por `cliente_id`, ordenando por `criado_em` e `id`); `item_pedido` (todas, somando `quantidade`) |
| Escreve | `cliente` (`nome`, `cpf_hash`, `telefone`, `endereco`); `pedido` (`cliente_id`, `endereco_entrega`, `forma_pagamento`, `total`); `item_pedido` (`pedido_id`, `produto_id`, `quantidade`, `preco_unitario`, `observacao`) |
| Nunca escreve em execução | `produto` — o cardápio só é populado pelo `seed.py`; e `pedido.status`, `cliente.criado_em` e `pedido.criado_em`, que ficam no default do banco |

O CPF em texto puro não é gravado em lugar nenhum: só o `cpf_hash`. Ver CLI-01.

## Ações e regras

- **Ninguém consulta o banco fora do `repositorio.py`.** Rota, WebSocket e o código da IA chamam as funções de lá; nenhum outro módulo monta query. A razão é concreta: é no repositório que o CPF vira hash antes de entrar na consulta (RNF06) e é lá que todo item extraído pelo modelo é validado contra o cardápio antes de virar linha (RIA04). Query espalhada pelo código significa, mais cedo ou mais tarde, CPF em texto puro num `WHERE` e pedido gravado com produto que não existe. Vale também o outro lado do RNF05: o repositório concentra o acesso a dados e deixa o pipeline de voz sem SQL dentro.
- Todo item passa por `buscar_produtos` antes de ir para o banco. Produto inexistente ou ambíguo aborta o `salvar_pedido` inteiro — nada é gravado pela metade.
- Validação acontece antes da transação: o `salvar_pedido` valida e calcula o total em memória e só então toca no banco, então erro de item nem chega a abrir escrita.
- Pedido e itens são gravados num único `commit`. Qualquer exceção leva `rollback`, e não fica pedido sem item no banco.
- Todo `except` de escrita faz `rollback` antes de seguir. Sem isso a sessão fica abortada e toda query seguinte morre, o que no WebSocket derrubaria a conversa inteira.
- `cpf_hash` é `UNIQUE`: não existem dois clientes com o mesmo CPF. O `criar_cliente` checa antes só para dar mensagem boa; a garantia real é a constraint.
- Quantidade é sempre inteira e maior que zero, no banco (`CHECK`) e no código. Quantidade quebrada ("uma pizza e meia") não é arredondada, é recusada.
- Forma de pagamento gravada é sempre uma das quatro de `FORMAS_PAGAMENTO`, ou nula. Não se grava o texto falado.
- Produto que sai do cardápio recebe `ativo = false`; nenhum produto é apagado.
- `preco_unitario` nunca é atualizado depois de gravado.

## Casos de borda

| Situação | Comportamento |
| --- | --- |
| CPF com dígito verificador errado, ou com número de dígitos diferente de 11 | `hashear_cpf` levanta `ValueError`; não chega a consultar o banco. Quem chama pede a repetição (CLI-01) |
| CPF não encontrado | `buscar_cliente_por_cpf` devolve `None` — é o caminho do RF04, cadastro na conversa |
| CPF já cadastrado no `criar_cliente` | `ValueError` apontando o `buscar_cliente_por_cpf`. Se escapar da checagem, o `IntegrityError` do `UNIQUE` vira `ValueError` depois do `rollback` |
| Nome vazio no cadastro | `ValueError`. Nome maior que 100 caracteres é cortado em 100 antes de tocar no banco |
| Telefone com mais de 20 dígitos | `ValueError`, para confirmar o número — evita o erro estourar só no `commit`, como erro de driver |
| Telefone com parêntese, traço ou palavra solta | `_so_digitos` guarda só os dígitos; string sem nenhum dígito vira `None` |
| Produto que o modelo inventou | `salvar_pedido` levanta `ValueError` e o pedido inteiro para; nada vai para o banco (RIA04) |
| Nome que casa com vários produtos ("pizza") | `ValueError` listando os candidatos, para o atendente perguntar. `buscar_produto` devolve `None` no mesmo caso |
| Quantidade quebrada (1.5) ou não numérica | `ValueError`; não arredonda, não assume |
| Quantidade zero ou negativa | `ValueError` no código e `CHECK (quantidade > 0)` no banco |
| Lista de itens vazia | `ValueError`; pedido sem item não é gravado |
| `cliente_id` que não existe | `ValueError` pedindo identificar ou cadastrar antes |
| Pedido sem endereço informado | Cai no `cliente.endereco` do cadastro; se o cliente também não tiver, a coluna aceita nulo |
| Forma de pagamento ambígua ("cartao", "maquininha"), ou com duas citadas | `ValueError` com a pergunta a fazer; nada é gravado |
| Forma de pagamento `None` | Aceita de propósito: o pedido nasce `aberto` e alguém fecha depois |
| Cliente novo, sem histórico | `historico_cliente` e `itens_mais_pedidos_do_cliente` devolvem lista vazia; o fallback é `itens_mais_pedidos_da_casa` |
| Produto desativado no histórico | Não aparece na recomendação: as duas funções de mais pedidos filtram `Produto.ativo`. O seed deixa a "Pizza de Escarola com Bacon" inativa justamente como caso de teste |
| Muitos pedidos no histórico | `historico_cliente` carrega os itens com `selectinload` numa consulta só, para não virar n+1 (uma query por pedido) |
| `banco.sql` alterado com o volume já criado | O Postgres ignora o arquivo e o banco continua com o esquema velho. Tem que rodar `npm run banco:recriar` (`docker compose down -v`) |
| `CPF_HMAC_SECRET` trocada depois de gravar clientes | Todos os `cpf_hash` do banco ficam inalcançáveis; nenhum cliente é mais encontrado pelo CPF. Ver CLI-01 |
| `AMBIENTE` diferente de `dev` sem `CPF_HMAC_SECRET` | O `config.py` levanta `RuntimeError` e o servidor não sobe |

## Fora de escopo

- Validação, normalização e hash do CPF, e o segredo HMAC: **CLI-01**.
- Regras de cardápio, recomendação e montagem do pedido na conversa: **PED-01**.
- Protocolo do WebSocket e o formato das mensagens: **PRO-01**.
- Tela de chamada: **ATD-01**.
- Docker, variáveis de ambiente e subida do servidor: **INF-01**.
- Medição de desempenho de consulta ou de qualquer etapa do pipeline: **MED-01**. Nada foi medido.
- Migrações versionadas (Alembic ou equivalente), backup, replicação e usuário de banco com permissão restrita: não implementado neste semestre. Hoje mudança de esquema significa recriar o volume e rodar o seed de novo.

## Questões em aberto

- O MER do documento oficial usa `id_cliente`, `data_cadastro` e `disponivel`; o banco usa `id`, `criado_em` e `ativo`. **Recomendação:** ajustar o documento para os nomes do código, porque o código já roda e está testado contra o Postgres — renomear coluna agora obrigaria a mexer em `banco.sql`, `models.py`, `repositorio.py` e `seed.py` para não ganhar nada.
- `pedido.status` tem default `aberto` e o seed grava `concluido`, mas nenhum código faz transição de estado: não existe lista fechada de valores nem quem os mude. **Recomendação:** fixar os estados junto com o RF11 (sugestão: `aberto` e `concluido`, mais `cancelado` se houver cancelamento na conversa) e decidir com o grupo se a transição vira função do repositório ou constraint no banco.
- `historico_cliente` traz 5 pedidos e as funções de mais pedidos trazem 3, por default escolhido no código, sem medição. **Recomendação:** revisar esses números quando a orquestração existir, olhando quanto de contexto cabe no prompt do Llama 3.2 3B sem estourar a meta de latência — decisão do MED-01, não deste item.
