# PED-01 Pedido e cardapio

Status: Parcial. As consultas de cardapio, o historico, a recomendacao, a interpretacao da forma de pagamento falada e a gravacao do pedido estao prontas em `backend/repositorio.py` e conferidas na mao contra o Postgres com os dados do `backend/seed.py`; nenhuma rota, websocket ou modulo de IA chama essas funcoes ainda, porque a orquestracao nao existe (VOZ-01).

Backlog: doc/backlog.md (PED-01). Requisitos: RF05, RF07, RF08, RF09, RF11, RIA04.

## Objetivo

O cliente fala o pedido em linguagem solta ("queria uma pizza de mussarela e uma coca") e o que chega do modelo de linguagem e texto, nao produto. Este item e a camada que transforma esse texto em linhas de banco: acha o produto no cardapio a partir do nome falado, responde duvida de produto e preco, puxa o historico para recomendar, interpreta a forma de pagamento dita em voz e grava pedido e itens numa transacao so. E tambem a barreira do RIA04: nada que nao esteja no cardapio ativo entra no pedido, e o que ficou ambiguo vira pergunta ao cliente em vez de escolha silenciosa do codigo.

## Usuarios e papeis

Item interno de backend, sem usuario final direto. Quem chama sao a orquestracao da conversa e o codigo da IA (VOZ-01), em nome do cliente que esta na chamada. O efeito visivel para o cliente e a resposta falada e o resumo do pedido no fim da chamada.

## Pontos de entrada

Tudo em `backend/repositorio.py`. Nenhuma rota HTTP ou frame de websocket chama essas funcoes hoje: `backend/main.py` nao importa `repositorio`.

| Funcao | Assinatura | Para que |
|---|---|---|
| `listar_cardapio` | `listar_cardapio(db, categoria=None, apenas_ativos=True)` | RF07: cardapio inteiro ou de uma categoria |
| `buscar_produtos` | `buscar_produtos(db, nome)` | RF07/RIA04: lista de candidatos para um nome falado |
| `buscar_produto` | `buscar_produto(db, nome)` | RF07/RIA04: o produto so quando ha um unico candidato |
| `historico_cliente` | `historico_cliente(db, cliente_id, limite=5)` | RF05: ultimos pedidos com os itens carregados |
| `itens_mais_pedidos_do_cliente` | `itens_mais_pedidos_do_cliente(db, cliente_id, limite=3)` | RF08: o "de sempre" do cliente |
| `itens_mais_pedidos_da_casa` | `itens_mais_pedidos_da_casa(db, limite=3)` | RF08: fallback para cliente novo |
| `interpretar_pagamento` | `interpretar_pagamento(forma_pagamento)` | RF09: forma de pagamento falada para valor canonico |
| `salvar_pedido` | `salvar_pedido(db, cliente_id, itens, endereco_entrega=None, forma_pagamento=None)` | RF09/RF11/RIA04: valida e grava |

Toda funcao que toca o banco recebe a `Session` pronta de fora; quem abre e fecha e o `get_db` de `backend/database.py`. Os imports sao planos (`from models import ...`), entao o codigo roda com `backend/` como diretorio de trabalho.

Para exercitar na mao, com o banco de pe e o seed aplicado:

```
npm run banco
npm run seed
cd backend
python -c "from database import SessionLocal; import repositorio as r; db = SessionLocal(); print(r.buscar_produtos(db, 'coca cola'))"
```

O servidor sobe com `npm run dev` (banco no Docker mais uvicorn na porta 3000) e a tela fica em `http://localhost:3000`, mas nada dessa tela chega aqui ainda.

## Telas

Nenhuma propria. O resumo do pedido do RF11 e exibido na tela de chamada, descrita em ATD-01.

## Escopo

### Consulta do cardapio por nome falado (pronto)

A transcricao nao devolve acento nem hifen de forma confiavel: o cliente fala "coca cola" e o cardapio tem "Coca-Cola 2 Litros". `_normalizar` resolve isso dos dois lados antes de comparar: `unicodedata.normalize("NFKD", ...)` derruba o acento, tudo vira minusculo e `re.sub(r"[^0-9a-z]+", " ", ...)` troca qualquer pontuacao por espaco. "Coca-Cola 2 Litros" vira `coca cola 2 litros`. O `ILIKE` do Postgres sozinho nao faz isso (ele nao ignora acento nem hifen), por isso `buscar_produtos` traz os ativos e compara em Python: o cardapio tem poucas dezenas de linhas (19 produtos no seed, 18 ativos).

`buscar_produtos` roda tres passos, na ordem, e devolve o primeiro que achar algo:

| Passo | Regra | Exemplo |
|---|---|---|
| 1 | nome normalizado igual ao termo | `pizza de mussarela` -> Pizza de Mussarela |
| 2 | termo contido no nome | `coca cola` -> Coca-Cola 2 Litros; `margherita` -> Pizza Margherita |
| 3 | nome contido no termo, quando a fala inteira veio junto | `queria uma pizza de mussarela` -> Pizza de Mussarela |

O passo 1 existe para o nome exato nunca virar duvida. Produto inativo nao entra em nenhum dos tres passos: a consulta base ja filtra `Produto.ativo.is_(True)`.

### Regra de ambiguidade, o coracao do RIA04 (pronto)

`buscar_produtos` devolve lista, nao produto. "pizza" casa com os 10 sabores ativos do seed, e escolher um deles no desempate seria entregar Margherita para quem so disse "quero uma pizza" e gravar pedido errado calado. Por isso:

- `buscar_produto` devolve o produto so quando ha exatamente um candidato; com zero ou com varios devolve `None`, de proposito.
- `salvar_pedido` trata os dois casos com mensagens diferentes: zero candidatos levanta `ValueError` dizendo que o produto nao existe no cardapio; mais de um levanta `ValueError` listando os nomes encontrados, para a orquestracao perguntar ao cliente qual deles.

Quem precisa perguntar usa `buscar_produtos` e le a lista; `buscar_produto` serve so para o caminho sem duvida.

### Consulta por categoria (pronto)

A categoria tambem vem da fala ("quais bebidas voces tem?"), no plural. `listar_cardapio` normaliza e tira o `s` final de cada palavra (`palavra.rstrip("s")`) antes do `ILIKE '%radical%'`: "bebidas" acha `bebida`, "pizzas" acha `pizza salgada` e `pizza doce`. Funciona porque as categorias do seed sao minusculas e sem acento (`pizza salgada`, `pizza doce`, `bebida`, `sobremesa`, `borda`); categoria acentuada cadastrada depois nao seria encontrada por esse caminho. Sem `categoria`, devolve o cardapio inteiro ordenado por categoria e nome. `apenas_ativos=False` inclui os desativados e existe para uso administrativo, nao para a conversa.

### Historico e recomendacao (pronto)

`historico_cliente` devolve os ultimos `limite` pedidos do cliente ordenados por `criado_em` decrescente (desempate por `id` decrescente), com os itens e os produtos ja carregados via `selectinload`/`joinedload` numa query so, para nao virar n+1 quando a IA montar o contexto.

`itens_mais_pedidos_do_cliente` agrupa por produto somando `item_pedido.quantidade` dos pedidos daquele cliente e devolve `[(Produto, quantidade_total)]` do mais pedido para o menos, desempatando por nome. `itens_mais_pedidos_da_casa` faz o mesmo sem filtrar por cliente. As duas filtram `Produto.ativo.is_(True)`: produto que saiu do cardapio nunca e recomendado, mesmo tendo sido campeao no passado.

O fallback e do chamador: cliente recem-cadastrado (RF04) nao tem pedido nenhum, `itens_mais_pedidos_do_cliente` devolve lista vazia e a recomendacao passa a usar `itens_mais_pedidos_da_casa`. O seed da base para isso: 6 clientes com 30 pedidos historicos e um produto favorito fixo por cliente, senao a recomendacao veria so itens soltos e nao teria o que recomendar. Qual produto lidera a casa depende do sorteio do seed (semente fixa, `SEMENTE = 10`) e nao esta medido aqui.

### Forma de pagamento falada (pronto)

Ninguem fala "cartao_credito" numa chamada. `interpretar_pagamento` traduz a frase para um dos quatro valores de `FORMAS_PAGAMENTO` (`pix`, `dinheiro`, `cartao_credito`, `cartao_debito`), os mesmos que o seed grava, e a coluna `pedido.forma_pagamento` e `VARCHAR(20)`. A ordem da decisao e: valor ja canonico, depois sinais por palavra, depois sinais ambiguos, depois erro.

Sinais reconhecidos, casados palavra a palavra sobre o texto normalizado:

| Fala do cliente | Texto normalizado | Resultado |
|---|---|---|
| "pix", "no pix" | `pix`, `no pix` | `pix` |
| "cartao_credito" (ja canonico) | `cartao credito` | `cartao_credito` |
| "vou pagar em dinheiro" | `vou pagar em dinheiro` | `dinheiro` |
| "em especie" | `em especie` | `dinheiro` |
| "dinheiro vivo" | `dinheiro vivo` | `dinheiro` |
| "dinheiro, troco para 100" | `dinheiro troco para 100` | `dinheiro` (o valor do troco e descartado) |
| "no cartao de credito", "credito" | `no cartao de credito` | `cartao_credito` |
| "no debito", "cartao de debito" | `no debito` | `cartao_debito` |

Casos que viram pergunta, e nao chute. Todos levantam `ValueError` com a pergunta pronta na mensagem:

| Fala do cliente | Por que para | Mensagem |
|---|---|---|
| "cartao" | nao diz credito nem debito | "cartao no credito ou no debito? pergunte ao cliente." |
| "na maquininha" | idem | a mesma mensagem |
| "dinheiro ou cartao de credito" | duas formas citadas, o cliente ainda nao decidiu | lista as formas encontradas e pede confirmacao |
| "boleto", "vale refeicao" | nenhum sinal conhecido | "nao reconhecida", seguido das quatro formas validas |
| `""`, `None` | veio vazio | "forma de pagamento vazia, pergunte ao cliente como ele vai pagar." |

`salvar_pedido` aceita `forma_pagamento=None` de proposito (o pedido nasce sem pagamento definido e alguem fecha depois), mas se vier qualquer coisa passa por esse mesmo crivo antes de qualquer escrita.

### Gravacao do pedido numa transacao (pronto)

`salvar_pedido` recebe `itens` como lista de dicionarios:

| Chave | Tipo | Obrigatoria | Observacao |
|---|---|---|---|
| `produto` | texto | sim | nome como o cliente falou; passa por `buscar_produtos` |
| `quantidade` | inteiro (texto com inteiro tambem serve) | nao, o padrao e 1 | numero quebrado e recusado |
| `observacao` | texto | nao | copiada para `item_pedido.observacao` |

A funcao valida tudo antes de tocar no banco: a forma de pagamento, a existencia do cliente, cada produto e cada quantidade. So depois monta o `Pedido` com os `ItemPedido` na relacao e faz um unico `commit`. Qualquer excecao no commit cai no `rollback`, que derruba pedido e itens juntos: nao fica pedido pela metade no banco. O preco e copiado do cardapio no momento da venda para `item_pedido.preco_unitario` (`Decimal(str(produto.preco))`), em vez de apontar para o preco de hoje; o total e somado em `Decimal` e gravado com `quantize(Decimal("0.01"))`. `endereco_entrega` cai no endereco cadastrado do cliente quando nao e informado. Depois do commit a funcao faz `refresh` e materializa `pedido.itens` com a sessao ainda aberta, porque quem chamou vai ler o resumo depois.

### Montagem do pedido ao longo da conversa (nao implementado)

O RF09 pede o pedido montado aos poucos, turno a turno, com o cliente adicionando, trocando e removendo item. O que existe hoje e a gravacao do pedido final. O estado da conversa, o acumulo dos itens entre turnos e a decisao de quando chamar `salvar_pedido` ficam na orquestracao (VOZ-01), que nao tem nenhuma linha escrita. O `status` do pedido tambem nao e tratado aqui (ver Questoes em aberto).

## Dados

Le:

| Tabela | Colunas | Onde |
|---|---|---|
| `produto` | `id`, `nome`, `categoria`, `preco`, `ativo` | `listar_cardapio`, `buscar_produtos`, as duas de mais pedidos |
| `pedido` | `id`, `cliente_id`, `criado_em` | `historico_cliente`, `itens_mais_pedidos_do_cliente` |
| `item_pedido` | `pedido_id`, `produto_id`, `quantidade` | historico e as duas de mais pedidos |
| `cliente` | `id`, `endereco` | `salvar_pedido`, para validar o cliente e herdar o endereco |

Escreve:

| Tabela | Colunas | Observacao |
|---|---|---|
| `pedido` | `cliente_id`, `endereco_entrega`, `forma_pagamento`, `total` | `status` e `criado_em` ficam no default do banco (`aberto` e `now()`) |
| `item_pedido` | `pedido_id`, `produto_id`, `quantidade`, `preco_unitario`, `observacao` | uma linha por item validado |

Nao escreve em `produto` nem em `cliente` (cadastro de cliente e CLI-01, esquema e DAD-01). Nao le nem grava CPF: aqui o cliente ja chega identificado por `cliente_id`.

## Acoes e regras

- Produto que nao esta no cardapio nunca entra no pedido: zero candidatos para o nome falado interrompe a gravacao inteira (RIA04).
- Produto inativo e tratado como inexistente em toda consulta da conversa: `buscar_produtos`, `itens_mais_pedidos_do_cliente` e `itens_mais_pedidos_da_casa` filtram `ativo = true`. O seed mantem "Pizza de Escarola com Bacon" desativada exatamente como caso de teste disso.
- Nome ambiguo nunca e desempatado pelo codigo: com mais de um candidato o pedido para e a mensagem traz a lista, para o atendente perguntar.
- Quantidade quebrada e recusada, nao truncada: `1.5` levanta erro em vez de virar `1`, porque truncar cobraria a menos calado.
- Quantidade tem que ser maior que zero, na aplicacao e no banco (`CHECK (quantidade > 0)` em `item_pedido`).
- Preco e copiado no momento da venda para `item_pedido.preco_unitario`; mudanca futura no cardapio nao altera pedido antigo.
- Dinheiro so em `Decimal`, nunca em `float`: as colunas sao `NUMERIC(10,2)` e o total e arredondado com `quantize(Decimal("0.01"))`.
- Forma de pagamento so e gravada se cair numa das quatro de `FORMAS_PAGAMENTO`; na duvida, erro com pergunta, nunca um valor escolhido no chute.
- Grava inteiro ou nao grava: um unico `commit` para pedido e itens, com `rollback` em qualquer falha. Toda validacao acontece antes do `add`, entao erro de item nem chega a abrir escrita.
- Pedido sem nenhum item nao e gravado.

## Casos de borda

| Entrada | Comportamento |
|---|---|
| `itens=[]` | `ValueError`: "pedido sem nenhum item, confirme o pedido com o cliente antes de salvar". Nada vai ao banco. |
| `quantidade=0` ou negativa | `ValueError`: a quantidade precisa ser maior que zero. O pedido inteiro para. |
| `quantidade=1.5` | `ValueError` avisando que a quantidade veio quebrada e pedindo quantas unidades o cliente quer. Nao arredonda. |
| `quantidade="2"` | Aceita: texto com inteiro e convertido. `"1.5"` como texto cai em "quantidade invalida". |
| `quantidade=None` | `ValueError` "quantidade invalida". Chave ausente, ao contrario, assume 1. |
| Produto inventado pelo modelo ("pizza de picanha") | Zero candidatos: `ValueError` "nao existe no cardapio, confirme com o cliente". Nenhuma linha gravada (RIA04). |
| Produto inativo ("escarola com bacon") | O mesmo caminho do inventado: nao existe para a conversa. |
| Produto ambiguo (`"pizza"` com 10 sabores ativos, `"borda"` com 2, `"2 litros"` com 2) | `ValueError` listando os candidatos, para perguntar ao cliente. |
| Termo generico com artigo (`"uma pizza"`) | Nao casa por nenhum dos tres passos e cai no erro de produto inexistente, nao no de ambiguidade. A extracao precisa entregar o nome do produto, nao a frase solta; a frase completa com o nome dentro ("queria uma pizza de mussarela") funciona pelo passo 3. |
| Nome vazio ou so pontuacao | `buscar_produtos` devolve lista vazia sem ir ao banco. |
| `cliente_id` inexistente | `ValueError` pedindo para identificar ou cadastrar antes (CLI-01). |
| Pagamento desconhecido, ambiguo ou duplo | `ValueError` antes de qualquer escrita, com a pergunta pronta (ver a tabela de pagamento). |
| "dinheiro ou cartao de credito" | Cai na regra de duas formas citadas, avaliada antes da regra do cartao ambiguo; por isso a entrada `"cartao de credito ou debito"` da lista `SINAIS_AMBIGUOS` nunca e alcancada. |
| Cliente sem endereco cadastrado e `endereco_entrega=None` | Grava com `endereco_entrega` nulo: a coluna aceita `NULL` e o codigo nao bloqueia. Exigir o endereco e responsabilidade da conversa (RF09). |
| Falha no commit (banco fora do ar, constraint) | `rollback` e a excecao sobe: nao fica pedido sem itens nem item orfao. |

Esses comportamentos foram exercitados na mao contra o Postgres local com os dados do seed. Nao existe arquivo de teste automatizado no repositorio e nenhum numero de acerto foi medido: a medicao do RIA04 e de MED-01.

## Fora de escopo

- Transcricao, modelo de linguagem, sintese, deteccao de fim de fala e a orquestracao que decide quando chamar estas funcoes: VOZ-01, nao implementado.
- Protocolo do websocket que leva pedido e resumo ate a tela: PRO-01.
- Tela de chamada e exibicao do resumo: ATD-01.
- Identificacao e cadastro do cliente e o tratamento do CPF: CLI-01.
- Esquema, modelos e seed em si: DAD-01.
- Medicao de acerto de extracao, de produto inexistente e de latencia: MED-01.
- Regras de negocio que nao existem neste semestre: estoque, cupom, desconto, taxa de entrega, pizza meia a meia, alteracao de pedido ja gravado e cancelamento no banco.

## Questoes em aberto

- O troco nao tem onde ser guardado. "dinheiro, troco para 100" e reconhecido como `dinheiro` e o valor 100 e descartado, porque `pedido` nao tem coluna para isso e `item_pedido.observacao` e do item, nao do pedido. Recomendacao: acrescentar `troco_para NUMERIC(10,2) NULL` na tabela `pedido` em `banco.sql`, junto com a proxima recriacao do volume (`npm run banco:recriar`), e fazer `interpretar_pagamento` devolver forma e troco em vez de so a forma. Enquanto isso nao for decidido, o troco fica apenas na confirmacao falada e nao e persistido, o que precisa estar claro para a banca.
- `salvar_pedido` nao define `status`: o pedido gravado nasce `aberto` pelo default do banco, enquanto o seed grava o historico como `concluido`. Recomendacao: o RF11 fechar a chamada gravando `concluido`, com o status passado explicitamente em `salvar_pedido`, e reservar `aberto` para pedido que ficou pela metade.
- `buscar_produto` devolve `None` tanto para "nao achei" quanto para "achei varios", e essa diferenca e justamente o que decide entre pedir para repetir e perguntar o sabor. Recomendacao: a orquestracao usar sempre `buscar_produtos` e olhar o tamanho da lista, deixando `buscar_produto` so para codigo que ja sabe que nao ha duvida.
