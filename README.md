# IARA

A IARA atende os pedidos de uma pizzaria por voz. O cliente abre a página, clica em Ligar e conversa como faria pelo telefone: diz o CPF, pergunta preço, escolhe os sabores e fala como vai pagar. No fim ela lê o pedido inteiro, e só grava depois que o cliente confirma.

Tudo roda no computador da pizzaria. O reconhecimento de fala, o modelo de linguagem, a voz e o banco de dados ficam na mesma máquina, sem API paga, e o áudio da conversa não é enviado para fora. A internet só é usada na instalação e na primeira chamada, para baixar as dependências e os modelos.

Este é o trabalho do Time 10 no Projeto Integrador VI, do curso de Engenharia de Software da PUC-Campinas, com orientação da professora Sílvia Cristina de Matos Soares.

## Como funciona

A tela grava o microfone e percebe sozinha quando a pessoa parou de falar, depois de 1,2 segundo de silêncio. O áudio vai para o servidor por WebSocket e o Whisper transforma a fala em texto.

Com o texto em mãos, quem decide o que fazer é o código em Python. Ele procura os produtos no cardápio, entende quantidades, tamanhos, trocas e forma de pagamento, e responde preços com o que está no banco. O Llama 3.2, que roda pelo Ollama, só é chamado quando essas regras não dão conta da fala. A resposta dele nunca altera o pedido diretamente.

Chegamos a esse formato depois de testar o contrário. Quando o modelo montava o pedido, ele inventava produtos e errava trocas, e em um notebook sem placa de vídeo cada resposta podia passar de 20 segundos.

A resposta vira áudio no Piper e volta para a tela, que também mostra a legenda da conversa e a comanda sendo preenchida.

## O que dá para fazer

Para pedir é preciso informar o CPF. Quem já tem cadastro é reconhecido pelo nome, e quem não tem faz o cadastro na própria conversa.

O cardápio de exemplo tem 27 sabores de pizza, bebidas, sobremesas e bordas. As pizzas são vendidas nos tamanhos pequena, média e grande, e os refrigerantes em lata, 600 ml ou 2 litros. Se o cliente não disser o tamanho, a IARA pergunta. Ela não faz pizza meio a meio e oferece uma de cada sabor no lugar.

Durante a conversa dá para trocar, tirar ou mudar itens, pedir sem cebola, mudar o endereço de entrega, pagar com Pix, cartão ou dinheiro com troco, perguntar o que foi pedido da última vez e pedir uma sugestão. A sugestão vem do histórico do cliente ou, se ele nunca pediu, dos itens mais vendidos.

Existe também um painel para o dono da pizzaria, em [localhost:3000/admin/](http://localhost:3000/admin/). Ele mostra o faturamento, os produtos mais vendidos, os últimos pedidos e as chamadas que estão acontecendo, com a transcrição e o tempo de cada etapa. Também é por lá que se acompanha o pedido depois da ligação: ele começa aberto, passa para em preparo, sai para entrega e termina como entregue, ou pode ser cancelado antes de sair. Como o painel ainda não tem login, os dados dele só são liberados no ambiente de desenvolvimento.

## Como rodar

Você vai precisar de Python 3.10 ou mais novo (usamos também o 3.14), Node.js, Docker Desktop e Ollama. Deixe o Docker e o Ollama abertos e, no PowerShell, dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm run deps
ollama pull llama3.2:3b
npm run banco
npm run seed
npm run dev
```

Depois abra [localhost:3000](http://localhost:3000) e libere o microfone.

O `npm run seed` só é necessário na primeira vez. Ele cadastra o cardápio, alguns clientes fictícios e pedidos antigos, e mostra no terminal os CPFs que podem ser usados nos testes. Nas próximas vezes basta o `npm run dev`, que também liga o banco.

Na primeira chamada o Whisper baixa o modelo `base`, então ela demora mais. A voz do Piper já vem no repositório, em `backend/agente/models/piper/`.

### Se você já tinha o banco de uma versão anterior

Estes comandos atualizam o banco sem apagar clientes nem pedidos. Rode nesta ordem. Eles podem ser executados mais de uma vez.

```powershell
docker cp database/migracao_tamanhos.sql pizzaria-db:/tmp/migracao_tamanhos.sql
docker exec pizzaria-db psql -U pizzaria -d pizzaria -f /tmp/migracao_tamanhos.sql
docker cp database/migracao_troco.sql pizzaria-db:/tmp/migracao_troco.sql
docker exec pizzaria-db psql -U pizzaria -d pizzaria -f /tmp/migracao_troco.sql
docker cp database/migracao_status.sql pizzaria-db:/tmp/migracao_status.sql
docker exec pizzaria-db psql -U pizzaria -d pizzaria -f /tmp/migracao_status.sql
docker cp database/migracao_integridade.sql pizzaria-db:/tmp/migracao_integridade.sql
docker exec pizzaria-db psql -U pizzaria -d pizzaria -f /tmp/migracao_integridade.sql
python backend/seed.py --completar
```

A migração de status troca o antigo `concluido` por `entregue` e encerra os pedidos que ficaram em `aberto` por mais de 12 horas. A de integridade cria regras para forma de pagamento, troco e preços. Se algum registro antigo quebrar uma delas, o Postgres informa qual foi e não aplica as regras até o registro ser corrigido.

Se não fizer questão dos dados, `npm run banco:recriar` apaga o banco e cria outro do zero. Depois dele, rode o `npm run seed` de novo.

### Quando algo não funciona

Se aparecer erro de senha para o usuário `pizzaria`, é provável que outro PostgreSQL instalado no Windows esteja usando a porta 5432. Pare esse serviço e suba o banco novamente.

Se a IARA responder perguntas simples e falhar em frases mais complicadas, confira se o Ollama está aberto e se o modelo foi baixado com `ollama list`.

## Configuração

O projeto roda sem nenhuma configuração na máquina de desenvolvimento. Estas variáveis de ambiente mudam o padrão:

| Variável | Para que serve |
| :-- | :-- |
| `DATABASE_URL` | Endereço do banco. O padrão é `postgresql+psycopg://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria`. |
| `AMBIENTE` | O padrão é `dev`, que libera o painel e a página de diagnóstico em `/teste`. |
| `CPF_HMAC_SECRET` | Segredo usado para proteger o CPF. É obrigatório fora do `dev` e não pode mudar depois que houver clientes cadastrados. |
| `OLLAMA_URL` | Endereço do Ollama. O padrão é `http://127.0.0.1:11434`. |
| `OLLAMA_MODEL` | Modelo de linguagem. O padrão é `llama3.2:3b`. Para usar outro, baixe antes com `ollama pull`. |
| `WHISPER_MODEL` | Tamanho do Whisper. O padrão é `base`. |
| `WHISPER_DEVICE` | O padrão é `cuda`. Sem placa NVIDIA, o Whisper passa a usar o processador. |

## Dados do cliente

O CPF não é gravado em texto. O banco guarda um hash HMAC-SHA256 gerado com o segredo da variável `CPF_HMAC_SECRET`, e é por ele que o cliente é encontrado. Na legenda da chamada e no painel, o CPF aparece como "CPF informado".

O modelo de linguagem não tem acesso ao banco. Todas as consultas e gravações passam por `backend/repositorio.py`.

## Onde fica cada coisa

A pasta `backend` tem o servidor e as regras da conversa. O arquivo principal é o `atendimento.py`, que conduz a chamada da saudação até a confirmação. Em `backend/agente` ficam a interpretação das falas, o prompt e os serviços de transcrição, linguagem e voz.

A tela da chamada está em `frontend` e o painel em `frontend/admin`. O esquema do banco e as migrações estão em `database`, e os testes em `tests`. A pasta `scripts/diagnostico` guarda uma página usada para testar o WebSocket sem a tela.

## Testes

```powershell
npm run teste
npm run teste:frontend
```

Os testes em Python usam um banco separado, chamado `pizzaria_teste`, que é recriado a cada execução. Sem o Docker aberto eles rodam em um SQLite temporário, mas antes de juntar branches vale rodar com o PostgreSQL. Nenhum deles substitui uma conversa de verdade pelo microfone.

## O que ainda falta

A IARA atende pelo navegador do computador e não está ligada a uma linha telefônica. O andamento do pedido é marcado à mão no painel, que ainda não tem login. O sistema também não calcula taxa nem prazo de entrega, e ainda não testamos várias chamadas ao mesmo tempo.

## Equipe

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | 24007131 |
