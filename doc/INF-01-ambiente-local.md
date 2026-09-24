# INF-01 Ambiente local

Status: pronto. Um integrante que formatou o PC chega da instalação do Git até a tela aberta em `http://localhost:3000` com banco populado, usando os scripts do `package.json`; o que ainda não existe é o pipeline de voz (VOZ-01), não o ambiente.
Backlog: doc/backlog.md (INF-01). Requisitos: RNF02, RNF06.

## Objetivo

Todo o resto do projeto depende de uma máquina com o Postgres de pé, as dependências Python instaladas e o servidor rodando. Sem um roteiro único, cada integrante monta o ambiente de um jeito, o banco de um fica diferente do banco do outro e o erro que aparece na máquina de quem está codando não reproduz na de quem está revisando. Este item fixa a sequência de instalação, os comandos oficiais (todos via `npm run`), o que cada um faz e o que fazer quando algum deles falha — que é a parte que mais custa tempo do grupo.

## Usuários e papéis

Item interno: os usuários são os cinco integrantes do time e a professora, no papel de quem precisa rodar o projeto na própria máquina. Não tem usuário final.

## Pontos de entrada

| Entrada | O que é |
| :-- | :-- |
| `passo_a_passo.txt` | roteiro curto de instalação, na raiz do repositório |
| `package.json` | onde estão todos os scripts (`dev`, `deps`, `banco`, `seed`, ...) |
| `docker-compose.yml` | define o container `pizzaria-db` (postgres:16) e monta o `banco.sql` |
| `banco.sql` | esquema do banco, aplicado no primeiro boot do container |
| `backend/config.py` | lê `DATABASE_URL`, `CPF_HMAC_SECRET` e `AMBIENTE` do ambiente |
| `backend/requirements.txt` | dependências Python instaladas pelo `npm run deps` |
| `backend/main.py` | aplicação FastAPI (`app`), carregada pelo uvicorn como `main:app` |
| `backend/seed.py` | popula o banco de desenvolvimento |
| `npm run dev` | comando único: sobe o banco e o servidor |
| `http://localhost:3000` | a tela, servida na raiz |
| `http://localhost:3000/health` | confirma que a API está de pé |

## Telas

Nenhuma. Item de infraestrutura. O `npm run dev` imprime o link da tela, que é descrita em ATD-01.

## Escopo

### 1. Instalar as ferramentas (pronto)

- Git: https://git-scm.com/downloads
- Docker Desktop: https://www.docker.com/products/docker-desktop
- Node.js (traz o `npm`, que roda os scripts do `package.json`): https://nodejs.org
- Python 3.11

Se o Docker avisar que falta o WSL, abrir o PowerShell como administrador, rodar o comando abaixo e reiniciar o PC:

```powershell
wsl --install
```

### 2. Baixar o projeto (pronto)

```bash
git clone https://github.com/RafssRv/PI_VI_TIME10.git
cd PI_VI_TIME10
```

### 3. Desligar o PostgreSQL local, se existir (pronto)

O container publica a porta 5432 em `127.0.0.1`. Se já houver um PostgreSQL instalado no Windows, os dois brigam pela mesma porta. No PowerShell como administrador, trocando `18` pela versão instalada:

```powershell
Stop-Service postgresql-x64-18
Set-Service postgresql-x64-18 -StartupType Manual
```

### 4. Instalar as dependências Python (pronto)

```bash
npm run deps
```

Roda `python -m pip install -r backend/requirements.txt`. O arquivo tem `fastapi==0.110.1`, `uvicorn==0.29.0`, `python-multipart==0.0.9`, `sqlalchemy==2.0.29`, `psycopg[binary]` e `websockets`. Não tem nada de voz: faster-whisper, Ollama e Piper entram em VOZ-01 e ainda não estão no `requirements.txt`.

### 5. Subir o banco (pronto)

Com o Docker Desktop aberto:

```bash
npm run banco
```

Roda `docker compose up -d`. Na primeira vez o Postgres executa o `banco.sql` sozinho e cria as tabelas. Conexão: `postgresql://pizzaria:pizzaria123@localhost:5432/pizzaria`.

### 6. Conferir as tabelas (pronto)

```bash
docker exec pizzaria-db psql -U pizzaria -d pizzaria -c "\dt"
```

Tem que aparecer: `cliente`, `item_pedido`, `pedido` e `produto`.

### 7. Popular o banco (pronto)

```bash
npm run seed
```

Roda `python backend/seed.py`. A semente do `random` é fixa (`SEMENTE = 10`), então todo mundo do time fica com exatamente o mesmo banco. Cria:

| O que | Quantidade | Detalhe |
| :-- | :-- | :-- |
| Produtos | 19 | 18 ativos e 1 inativo (`Pizza de Escarola com Bacon`) |
| Clientes | 6 | nome, telefone, endereço e `cpf_hash` |
| Pedidos | 30 | status `concluido`, espalhados pelos últimos 5 meses |
| Itens de pedido | variável | cada pedido tem o produto favorito do cliente mais 0 a 3 extras |

No final o script imprime os CPFs de teste, que é o que se usa para exercitar a identificação por voz:

| CPF impresso | Para que serve |
| :-- | :-- |
| os 6 CPFs dos clientes criados | testar RF03: o CPF existe, a busca tem que achar o cadastro e o histórico |
| 1 CPF extra, que não está no banco | testar RF04: o CPF não é encontrado e o sistema tem que cadastrar durante a conversa |

O script também lembra na saída que `Pizza de Escarola com Bacon` está inativa: é o produto que o modelo pode citar mas nunca pode vender, caso de teste do RIA04.

Se o banco já tiver produtos, o seed não duplica nada — ele imprime `o banco ja tem N produtos, nao vou duplicar nada.` e sai. Para apagar e popular de novo:

```bash
npm run seed:recriar
```

Isso roda `python backend/seed.py --recriar`, que apaga na ordem das chaves estrangeiras (`item_pedido`, `pedido`, `cliente`, `produto`) e insere tudo outra vez. Ele apaga as linhas, não as tabelas: o esquema continua o mesmo.

### 8. Subir o servidor (pronto)

```bash
npm run dev
```

O script faz três coisas em sequência: `docker compose up -d`, imprime `Tela: http://localhost:3000` e sobe `python -m uvicorn main:app --reload --port 3000 --log-level warning --no-access-log` de dentro da pasta `backend`. A tela fica na **raiz**, `http://localhost:3000` — não existe mais `/app`.

Rotas publicadas pelo `backend/main.py`:

| Rota | Método | O que faz |
| :-- | :-- | :-- |
| `/` e demais arquivos | GET | serve a pasta `frontend/` (`StaticFiles`, com `html=True`) |
| `/health` | GET | devolve `{"status": "ok", ...}`, usado para confirmar que a API subiu |
| `/teste` | GET | serve `backend/teste_ws.html`, página de teste do WebSocket |
| `/api/v1/falar` | POST | recebe um arquivo de áudio inteiro e devolve o mesmo arquivo (mock) |
| `/ws/falar` | WebSocket | canal de streaming; o protocolo é de PRO-01 |

O `mount` da pasta `frontend` é declarado por último de propósito, para que as quatro rotas acima sejam casadas antes.

### Scripts do package.json (pronto)

| Script | Comando | Para que serve |
| :-- | :-- | :-- |
| `npm run dev` | `docker compose up -d` + uvicorn na porta 3000 | o comando do dia a dia: sobe tudo |
| `npm run deps` | `python -m pip install -r backend/requirements.txt` | instala as dependências Python |
| `npm run banco` | `docker compose up -d` | só liga o banco (ex.: depois de reiniciar o PC) |
| `npm run banco:parar` | `docker compose down` | desliga o container e **mantém** os dados |
| `npm run banco:recriar` | `docker compose down -v` + `up -d` | apaga o volume e recria o banco do zero |
| `npm run seed` | `python backend/seed.py` | popula o banco (não duplica se já houver dados) |
| `npm run seed:recriar` | `python backend/seed.py --recriar` | apaga as linhas e popula de novo |

### Mexeu no banco.sql: tem que recriar (pronto)

O `docker-compose.yml` monta o `banco.sql` em `/docker-entrypoint-initdb.d`. O Postgres só executa esse diretório quando o volume de dados está **vazio**. Consequência prática: editar o `banco.sql` e dar `npm run banco` não muda nada — o banco continua com o esquema velho e o erro só aparece depois, como coluna que não existe.

```bash
npm run banco:recriar
npm run seed
```

`npm run banco:parar` (sem `-v`) não serve para isso: ele derruba o container mas preserva o volume `pgdata`.

### Variável CPF_HMAC_SECRET (pronto)

O CPF nunca é gravado em texto puro (RNF06). O `backend/seguranca.py` grava em `cliente.cpf_hash` o HMAC-SHA256 do CPF, usando como chave o `SEGREDO_CPF` do `backend/config.py`, que vem da variável de ambiente `CPF_HMAC_SECRET`. O motivo de ser HMAC com segredo e não SHA-256 puro está no código: CPF tem cerca de 10⁹ combinações, então hash sem segredo se quebra por força bruta.

Para definir antes de subir o servidor:

```powershell
$env:CPF_HMAC_SECRET = "um-segredo-bem-grande"
```

```bash
export CPF_HMAC_SECRET="um-segredo-bem-grande"
```

Comportamento quando a variável não está definida, controlado pelo `AMBIENTE` (padrão `dev`):

| `AMBIENTE` | `CPF_HMAC_SECRET` ausente |
| :-- | :-- |
| `dev` (padrão) | usa o segredo de desenvolvimento, que está versionado no repositório, e imprime um aviso no import do módulo |
| qualquer outro valor | levanta `RuntimeError` e o servidor não sobe |

**Trocar o segredo invalida todos os `cpf_hash` já gravados.** O hash é calculado com a chave, então o mesmo CPF com outra chave produz outro hexdigest: os clientes que estão no banco deixam de ser encontrados pela busca por CPF e a identificação (RF03) passa a cair no cadastro (RF04) para todo mundo. Quem trocar o segredo tem que rodar `npm run seed:recriar` em seguida, para regravar os hashes com a chave nova.

### O uvicorn roda de dentro da pasta backend (pronto)

Os imports do backend são planos: `database.py` faz `from config import URL_DO_BANCO`, `seguranca.py` faz `from config import SEGREDO_CPF`, `seed.py` faz `from database import SessionLocal`. Não existe pacote, não existe `__init__.py`, não existe import relativo. Por isso a pasta `backend` precisa ser o diretório de trabalho: é de lá que o uvicorn encontra o módulo `main` e é de lá que os módulos se enxergam.

O script `dev` já faz o `cd backend` antes de chamar o uvicorn, então quem usa `npm run dev` não precisa pensar nisso. Quem chama o uvicorn na mão a partir da raiz toma erro de import.

O `npm run seed` roda da raiz sem problema porque o Python coloca a pasta do script (`backend/`) no início do `sys.path`.

## Dados

O ambiente em si não tem dado próprio. O que ele manipula:

| Ação | Tabela | Colunas |
| :-- | :-- | :-- |
| `npm run seed` escreve | `produto` | `nome`, `descricao`, `categoria`, `preco`, `ativo` |
| `npm run seed` escreve | `cliente` | `nome`, `cpf_hash`, `telefone`, `endereco` |
| `npm run seed` escreve | `pedido` | `cliente_id`, `endereco_entrega`, `forma_pagamento`, `status`, `total`, `criado_em` |
| `npm run seed` escreve | `item_pedido` | `pedido_id`, `produto_id`, `quantidade`, `preco_unitario`, `observacao` |
| `npm run seed` lê | `produto` | `count()`, para não duplicar dados |
| `npm run banco:recriar` apaga | volume `pgdata` | todas as tabelas, incluindo o esquema |

O esquema das tabelas é de DAD-01. O `/ws/falar` grava `audio_cliente_streaming.webm` e o `/api/v1/falar` grava `temp_<nome do arquivo>` na pasta em que o servidor está rodando (`backend/`); são arquivos de mock, não dado de projeto.

## Ações e regras

- Nenhum comando de banco roda sem o Docker Desktop aberto: `npm run banco` e `npm run dev` falham na primeira linha.
- A porta 5432 é publicada em `127.0.0.1`, não em `0.0.0.0`: o banco não fica exposto na rede local.
- Mudança em `banco.sql` só tem efeito depois de `npm run banco:recriar`; `npm run banco` sozinho nunca reaplica o arquivo.
- `npm run banco:parar` não pode apagar dado: ele roda `docker compose down` sem `-v`.
- O `npm run seed` nunca duplica: ele conta os produtos antes e só insere se a tabela estiver vazia, a menos que venha `--recriar`.
- O seed nunca grava CPF em texto puro: o número só existe em memória e na saída do terminal; no banco entra o `cpf_hash`.
- O seed nunca coloca produto inativo em pedido: só entram produtos com `ativo = true`.
- O seed é tudo ou nada: um único `commit` no final e `rollback` em qualquer exceção.
- Fora do ambiente `dev`, o servidor não sobe sem `CPF_HMAC_SECRET` definida.
- O uvicorn sempre roda com `backend/` como diretório de trabalho.
- A tela fica na raiz. Nenhum caminho `/app` é válido.

## Casos de borda

| Sintoma | Causa | Solução |
| :-- | :-- | :-- |
| O uvicorn não sobe e reclama que o endereço já está em uso (porta 3000) | outro processo ocupa a 3000, normalmente um `npm run dev` que ficou aberto em outro terminal | fechar o terminal antigo; achar o processo com `netstat -ano \| findstr :3000` e encerrá-lo pelo Gerenciador de Tarefas |
| O `docker compose up -d` falha dizendo que a porta 5432 não está disponível | PostgreSQL instalado no Windows ocupando a mesma porta | executar o passo 3 (`Stop-Service postgresql-x64-NN`) |
| Qualquer comando de banco reclama que não consegue falar com o Docker | Docker Desktop fechado ou ainda subindo | abrir o Docker Desktop, esperar o ícone ficar estável e repetir o comando |
| `npm run seed` imprime `ERRO: nao consegui ler a tabela produto.` | o container subiu mas o `banco.sql` não rodou (volume criado antes do arquivo existir, ou esquema antigo) | `npm run banco:recriar` e depois `npm run seed` |
| A tela abre, mas as consultas não acham cliente nem cardápio | banco de pé e vazio: ninguém rodou o seed | `npm run seed` |
| O cadastro do cliente que já existia deixa de ser encontrado depois de mexer na configuração | `CPF_HMAC_SECRET` mudou, então os `cpf_hash` gravados não batem mais | voltar o segredo anterior, ou `npm run seed:recriar` com o segredo novo |
| O navegador não deixa usar o microfone | permissão negada para o site | clicar no cadeado ao lado do endereço e permitir o microfone; comportamento da tela em ATD-01 |
| Abrindo pelo IP da máquina na rede (`http://192.168.x.x:3000`) o microfone nem é oferecido | o navegador só libera captura de microfone em origem segura: HTTPS ou `localhost` | usar `http://localhost:3000` na própria máquina |
| O uvicorn não encontra o módulo `main` | foi chamado na mão a partir da raiz do repositório | usar `npm run dev`, ou entrar em `backend/` antes de chamar o uvicorn |
| `npm run ...` não é reconhecido | Node.js não instalado | instalar o Node.js (passo 1) |

## Fora de escopo

- O esquema e as tabelas em si: DAD-01.
- A tela, os estados dela e o comportamento do microfone na interface: ATD-01.
- O protocolo do WebSocket `/ws/falar`: PRO-01.
- Instalação e download dos modelos de voz (faster-whisper, Ollama/Llama 3.2, Piper): VOZ-01. Nada disso está no `requirements.txt` nem no `docker-compose.yml` hoje.
- Medição de tempo de subida, de latência ou de consumo de recurso: MED-01.
- Deploy, servidor de produção, HTTPS e acesso de fora da máquina: fora do semestre. O escopo é chamada simulada, em desktop, no navegador da própria máquina.

## Questões em aberto

- A versão do Python não está fixada em lugar nenhum do repositório; o time trabalha com a 3.11, mas nada no código obriga. Recomendação: registrar a versão mínima no `requirements.txt` ou no README, e todo mundo usar a mesma antes de VOZ-01, que é onde a compatibilidade de pacote costuma quebrar.
- `psycopg[binary]` e `websockets` estão sem versão no `requirements.txt`, então duas máquinas instaladas em datas diferentes podem ficar com versões diferentes. Recomendação: fixar as duas versões como já está feito para fastapi, uvicorn e sqlalchemy.
- Não está decidido se o time compartilha um valor único de `CPF_HMAC_SECRET` ou se cada um fica com o segredo de desenvolvimento. Recomendação: cada um fica com o padrão de `dev` na máquina local, já que o banco é recriável pelo seed; um segredo combinado só faria falta se fôssemos compartilhar dump de banco.
- O `README.md` ainda manda rodar só `docker compose up -d` e não cita `npm run deps`, `npm run dev`, o seed nem a tela na raiz. Recomendação: atualizar o README para apontar para este item, em vez de manter dois roteiros que vão divergir.
- Não há medição de quanto tempo leva montar o ambiente do zero nem de quanto o Docker consome com o Postgres de pé. Recomendação: a medir junto com MED-01, se a banca pedir.
