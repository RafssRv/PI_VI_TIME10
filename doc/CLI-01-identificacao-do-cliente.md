# CLI-01 Identificacao e cadastro do cliente

Status: Parcial. A cadeia tecnica do CPF esta pronta e testada contra o Postgres (normalizacao, validacao dos digitos verificadores, hash HMAC-SHA256, busca e cadastro em `backend/seguranca.py` e `backend/repositorio.py`); o que nao existe e a conversa que chama essas funcoes, porque o pipeline de voz e a orquestracao ainda nao foram escritos, e a confirmacao verbal exigida pelo RIA02 tambem nao existe no codigo.
Backlog: doc/backlog.md (CLI-01). Requisitos: RF03, RF04, RNF06; encosta no RIA02.

## Objetivo

O atendente precisa saber com quem esta falando antes de montar qualquer pedido: e o cadastro do cliente que traz o endereco de entrega e que da acesso ao historico que sustenta a recomendacao (RF05 e RF08, em PED-01). A chave dessa identificacao e o CPF, e ele chega pelo pior canal possivel: transcricao de fala. Este item resolve o caminho inteiro entre o numero falado e a linha da tabela `cliente`: limpar o que a transcricao trouxe junto, recusar numero que nao fecha nos digitos verificadores, transformar em hash antes de encostar no banco, achar o cliente por esse hash e, quando nao achar, cadastrar sem interromper a conversa. O CPF em si nunca e gravado (RNF06).

## Usuarios e papeis

O cliente que liga e fala o nome e o CPF. Nao ha papel de operador, administrador ou tela de cadastro manual: o unico caminho de cadastro previsto neste semestre e a propria conversa (RF04). O time usa as mesmas funcoes fora da conversa em `backend/seed.py`, para popular o banco de desenvolvimento.

## Pontos de entrada

| Onde | O que e |
| :-- | :-- |
| `backend/seguranca.py` | `normalizar_cpf(cpf)`, `cpf_valido(cpf)`, `hashear_cpf(cpf)` |
| `backend/repositorio.py` | `buscar_cliente_por_cpf(db, cpf)` (RF03), `criar_cliente(db, nome, cpf, telefone=None, endereco=None)` (RF04) |
| `backend/config.py` | `SEGREDO_CPF` (variavel de ambiente `CPF_HMAC_SECRET`) e `AMBIENTE` |
| `backend/database.py` | `get_db()` e `SessionLocal`, que abrem e fecham a `Session` passada nas funcoes acima |
| `backend/models.py` e `banco.sql` | classe `Cliente` e tabela `cliente` |
| `backend/seed.py` | `gerar_cpf(base)` monta os CPFs ficticios e grava os 6 clientes ja hasheados |

Comandos:

```bash
npm run dev     # sobe o postgres no docker e o uvicorn na porta 3000
npm run seed    # popula cardapio, 6 clientes e 30 pedidos historicos
```

Nenhuma rota HTTP e nenhum frame do WebSocket chama `buscar_cliente_por_cpf` ou `criar_cliente` hoje: `backend/main.py` nao importa `repositorio`. As funcoes existem, foram exercitadas contra o banco pelo seed, e estao esperando a orquestracao (VOZ-01) para entrar na conversa.

## Telas

A identificacao acontece dentro da chamada, na tela unica do projeto, que esta em reescrita. A tela e descrita em ATD-01; este item nao repete nada sobre ela. O CPF nunca e digitado: ele e falado.

## Escopo

### Normalizacao do que a transcricao entrega (pronto)

A fala do CPF nao chega ao codigo como onze digitos limpos. O faster-whisper devolve pontuacao, traco, espaco e palavra solta no meio do numero. `normalizar_cpf` joga fora tudo que nao e digito e devolve so os numeros:

```python
return re.sub(r"\D", "", str(cpf))
```

Entrada `None` vira string vazia em vez de estourar, porque o valor pode chegar ausente do JSON que o modelo produzir. A funcao nao tenta adivinhar nada alem disso: nao converte numero por extenso, nao corrige digito, nao completa com zero. Numero por extenso ("trezentos e oitenta e dois") e problema da transcricao e do prompt do modelo, nao daqui.

### Validacao dos dois digitos verificadores (pronto)

`cpf_valido` roda o algoritmo oficial: para 9 e depois para 10 digitos, soma cada digito multiplicado por um peso que comeca em `quantidade + 1` e decresce, tira `(soma * 10) % 11`, troca resto 10 por 0 e compara com o digito verificador correspondente. Antes disso recusa duas coisas: comprimento diferente de 11 e os onze digitos iguais (`digitos == digitos[0] * 11`), que passam na conta do DV mas nao sao CPF de ninguem.

Validar o DV aqui nao e formalidade. O numero veio de reconhecimento de fala, e o erro tipico e a troca de um digito por outro de som parecido. O digito verificador pega quase toda troca de um digito antes de a consulta sair do processo. Sem essa checagem, o comportamento diante de um erro de transcricao seria uma busca que nao acha nada, seguida de um cadastro novo com o numero errado: o cliente perderia o proprio historico e o banco ganharia um duplicado que ninguem consegue localizar depois, porque o CPF esta hasheado e nao da para inspecionar a olho. Com a checagem, o erro vira um pedido de repeticao na hora, que e tambem o comportamento que o RIA09 exige.

### Hash HMAC-SHA256 com segredo (pronto)

`hashear_cpf` normaliza, exige 11 digitos, exige DV valido e so entao devolve o hexdigest de 64 caracteres que vai para `cliente.cpf_hash`:

```python
return hmac.new(SEGREDO_CPF.encode("utf-8"), digitos.encode("utf-8"), hashlib.sha256).hexdigest()
```

Quando o CPF nao presta, a funcao levanta `ValueError` com a mensagem ja pronta para quem chama repassar ao cliente. Nenhuma dessas mensagens contem o numero: a de comprimento cita a quantidade de digitos recebida, a de DV nao cita nada.

Por que nao SHA-256 puro:

| | SHA-256 puro | HMAC-SHA256 com segredo |
| :-- | :-- | :-- |
| Espaco de busca | cerca de 10^9 CPFs validos, conhecido e enumeravel | o mesmo espaco, mas cada tentativa depende do segredo |
| Vazamento so do banco | da para pre-computar a tabela inteira e reverter todo `cpf_hash` | nao ha o que pre-computar sem o segredo |
| O que precisa vazar | so a tabela | a tabela e o segredo, que nao esta no banco |
| RNF06 cumprido | na aparencia | de fato |

O ponto e o tamanho do espaco. CPF tem 11 digitos, mas dois sao verificadores: sobram da ordem de 10^9 numeros validos. Isso e pequeno demais para hash sem segredo, porque enumerar 10^9 entradas de SHA-256 e trabalho rapido em hardware comum e o resultado e a lista inteira de `hash -> CPF`. O segredo muda o jogo porque ele nao mora no banco: quem levar um dump da tabela `cliente` leva 64 caracteres de hex por linha e nada mais. Essa e a razao de o `config.py` recusar subir o servidor sem `CPF_HMAC_SECRET` quando `AMBIENTE` nao e `dev` (levanta `RuntimeError`) e de imprimir aviso quando cai no segredo de desenvolvimento, que esta versionado no repositorio: HMAC com segredo publico vale exatamente o mesmo que SHA-256 puro.

Consequencia aceita: o hash nao volta. Nao existe "qual e o CPF desse cliente" no sistema, so "esse CPF e esse cliente". Para o escopo do semestre isso basta, porque o CPF serve unicamente de chave de identificacao.

### Busca do cliente (pronto, RF03)

```python
def buscar_cliente_por_cpf(db, cpf):
    cpf_hash = hashear_cpf(cpf)
    return db.query(Cliente).filter(Cliente.cpf_hash == cpf_hash).first()
```

Recebe o CPF como o cliente falou, hasheia e compara hash com hash. Devolve o `Cliente` ou `None`. `None` nao e erro: e o gatilho do RF04. CPF invalido nao chega a virar consulta, porque o `hashear_cpf` estoura antes.

### Cadastro durante a conversa (pronto, RF04)

`criar_cliente` faz, nesta ordem: tira espaco do nome e recusa nome vazio; corta o nome em 100 caracteres; reduz o telefone a digitos com `_so_digitos` e recusa mais de 20; hasheia o CPF; confere se ja existe cliente com aquele hash; insere e faz commit dentro de `try`, com `rollback` tanto no `IntegrityError` quanto em qualquer outra excecao.

Os cortes de tamanho existem porque `cliente.nome` e `VARCHAR(100)` e `cliente.telefone` e `VARCHAR(20)`: sem validar no Python, o estouro so apareceria no commit, como erro de driver, no meio da chamada. O `rollback` do bloco generico tambem nao e enfeite: sem ele a `Session` fica abortada e toda query seguinte morre, o que derrubaria a conversa inteira e nao so o cadastro.

A checagem previa de duplicado serve para dar mensagem boa; a garantia de verdade e o `UNIQUE` de `cliente.cpf_hash`, que pega inclusive a corrida entre duas sessoes cadastrando o mesmo CPF ao mesmo tempo.

### Confirmacao verbal do CPF (nao implementado, RIA02)

O RIA02 exige que o CPF reconhecido por voz seja confirmado com o cliente antes de valer. Isso nao existe no codigo: hoje qualquer chamador que passe um CPF para `buscar_cliente_por_cpf` esta tratando a primeira transcricao como definitiva. O DV cobre parte do risco, porque erro de um digito quase sempre quebra a conta, mas nao cobre a troca que por acaso resulta em outro CPF valido. A confirmacao entra junto com a orquestracao, em VOZ-01, e o acerto depois dela e medido em MED-01.

### Ligacao com a conversa (nao implementado)

Quem pergunta o nome e o CPF, em que turno, e o que o atendente responde depois de identificar sao decisoes da orquestracao (VOZ-01) e do protocolo (PRO-01). Este item entrega as funcoes e as invariantes; nao entrega dialogo.

## Dados

Tabela `cliente`, a unica tocada por este item.

| Coluna | Tipo | Escrita por | Observacao |
| :-- | :-- | :-- | :-- |
| `id` | `SERIAL PRIMARY KEY` | Postgres | |
| `nome` | `VARCHAR(100) NOT NULL` | `criar_cliente` | vem da fala, cortado em 100 |
| `cpf_hash` | `VARCHAR(64) NOT NULL UNIQUE` | `criar_cliente` | hexdigest do HMAC-SHA256; e o campo lido em `buscar_cliente_por_cpf` |
| `telefone` | `VARCHAR(20)` | `criar_cliente` | so digitos, opcional |
| `endereco` | `TEXT` | `criar_cliente` | opcional; vira o padrao de `endereco_entrega` em PED-01 |
| `criado_em` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | Postgres | |

Le: `cliente` por `cpf_hash`. Escreve: uma linha em `cliente` por cadastro. Nao existe coluna de CPF em texto puro em lugar nenhum do esquema. Nao ha `UPDATE` nem `DELETE` de cliente neste item; alteracao de cadastro por voz nao foi implementada.

## Acoes e regras

- CPF em texto puro nunca e gravado. A unica coluna que o representa e `cliente.cpf_hash`.
- CPF em texto puro nunca entra em log da aplicacao. As `ValueError` de `hashear_cpf` citam a quantidade de digitos ou nada, nunca o numero, e nem `seguranca.py` nem `repositorio.py` imprimem o CPF. Excecao consciente: `backend/seed.py` imprime no terminal os CPFs ficticios que ele mesmo gerou, para o time testar o RF03 e o RF04; sao dados inventados e nao passam por conversa nenhuma.
- CPF invalido nunca vira consulta ao banco: `hashear_cpf` levanta `ValueError` antes de qualquer query, e as duas funcoes do repositorio comecam por ele.
- Trocar `CPF_HMAC_SECRET` invalida todos os `cpf_hash` ja gravados. Nao existe migracao possivel, porque o hash nao volta: com segredo novo, cliente antigo nunca mais e encontrado e vira cadastro duplicado. Quem trocar o segredo tem que repopular o banco (`npm run seed:recriar`) ou aceitar recadastrar todo mundo.
- Fora de `AMBIENTE=dev`, o servidor nao sobe sem `CPF_HMAC_SECRET`. Em `dev` sem a variavel, ele usa o segredo versionado e imprime aviso uma vez, no import do `config.py`.
- Dois clientes nao podem ter o mesmo CPF. A garantia e o `UNIQUE` do banco; a checagem em Python serve so para a mensagem.
- Cliente nao e cadastrado sem nome: `criar_cliente` recusa nome vazio ou so com espaco.
- Todo commit que falha faz `rollback`, para nao deixar a `Session` abortada e derrubar a conversa.
- Ninguem consulta a tabela `cliente` fora de `backend/repositorio.py`. E a regra que impede CPF em texto puro aparecer numa query solta.

## Casos de borda

| Situacao | O que o codigo faz | O que o atendente deve falar (ainda nao implementado) |
| :-- | :-- | :-- |
| Menos de 11 digitos | `hashear_cpf` levanta `ValueError` citando quantos vieram | avisar que faltou numero e pedir o CPF de novo, devagar, em grupos de tres |
| Mais de 11 digitos | a mesma `ValueError`, com a contagem | a mesma coisa: provavel numero colado na fala seguinte, pedir de novo |
| CPF vazio ou `None` | normaliza para string vazia e cai no caso de comprimento, com 0 digitos | perguntar o CPF |
| DV nao bate | `cpf_valido` devolve `False` e `hashear_cpf` levanta `ValueError` | dizer que nao entendeu direito e pedir para repetir; o mais provavel e erro de transcricao, nao erro do cliente |
| Todos os digitos iguais (`11111111111`) | recusado antes do calculo do DV | tratar como numero nao entendido e pedir de novo |
| CPF valido, nao cadastrado | `buscar_cliente_por_cpf` devolve `None` | seguir para o RF04: pedir o nome e cadastrar na hora, sem mandar o cliente para outro canal |
| CPF ja existe, mas chamaram `criar_cliente` | `ValueError` "ja existe cliente com esse cpf" | nao e caso de falar nada ao cliente: e erro de fluxo, o codigo deveria ter usado `buscar_cliente_por_cpf` |
| Dois cadastros do mesmo CPF ao mesmo tempo | `IntegrityError` do `UNIQUE`, `rollback` e `ValueError` | cumprimentar pelo cadastro que ficou, sem expor o erro |
| Nome vazio no cadastro | `ValueError` antes de tocar no banco | perguntar o nome antes de continuar |
| Telefone com mais de 20 digitos | `ValueError` citando os digitos do telefone | pedir o telefone de novo |
| CPF de outra pessoa, valido por acaso | o codigo nao tem como perceber: acha o cliente e devolve | risco real, coberto so pela confirmacao verbal do RIA02, que ainda nao existe (ver Questoes em aberto) |
| Banco fora do ar | a excecao do driver sobe para quem chamou; este item nao trata | tratamento de indisponibilidade e de INF-01 e VOZ-01 |

## Fora de escopo

- Captura do audio, transcricao e sintese: VOZ-01.
- Frames que carregam nome e CPF entre tela e servidor: PRO-01.
- A tela da chamada: ATD-01.
- Cardapio, montagem e gravacao do pedido: PED-01.
- Esquema completo do banco e demais tabelas: DAD-01.
- Docker, variaveis de ambiente e subida do servidor: INF-01.
- Medicao do acerto do CPF depois da confirmacao: MED-01.
- LGPD completa, politica de retencao, direito de exclusao, cifragem reversivel do CPF, autenticacao com senha e alteracao de cadastro por voz: nada disso esta previsto neste semestre.

## Questoes em aberto

- Onde fica o segredo no dia da apresentacao. Hoje, sem `CPF_HMAC_SECRET` definida, o sistema roda com o segredo de desenvolvimento que esta versionado no GitHub, o que anula na pratica o RNF06. Recomendacao: definir `CPF_HMAC_SECRET` na maquina da apresentacao antes de qualquer coisa e, na mesma sessao de terminal, rodar `npm run seed:recriar` e so depois `npm run dev`; se o seed rodar com um segredo e o servidor com outro, nenhum cliente do seed e encontrado. Manter `AMBIENTE=dev` na maquina de cada um e usar outro valor na maquina da apresentacao, para que o servidor recuse subir com o segredo publico. O valor nao vai para o repositorio: fica no terminal de quem apresenta, com um integrante guardando copia caso a maquina reinicie.
- Confirmacao verbal do CPF (RIA02). Nao existe no codigo, e sem ela o risco do CPF valido de outra pessoa fica descoberto. Recomendacao: a orquestracao repetir o CPF em voz, em grupos de tres digitos, e so chamar `buscar_cliente_por_cpf` depois da confirmacao do cliente; implementar junto com VOZ-01 e contar o acerto pos-confirmacao em MED-01, que e a evidencia que o RIA02 pede.
- Como confirmar que o cadastro encontrado e mesmo daquele cliente. O atendente anunciar o nome ("achei seu cadastro, Carlos") entrega o nome de um terceiro para quem errou o CPF. Recomendacao: pedir o nome antes do CPF e comparar com o do cadastro no servidor, respondendo so "achei seu cadastro" quando bater e pedindo o CPF de novo quando nao bater; o quanto exigir na comparacao (nome inteiro ou primeiro nome) fica para o grupo decidir com a professora.
