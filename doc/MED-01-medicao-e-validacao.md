# MED-01 Medicao e validacao

Status: nao iniciado. Nenhuma ferramenta de medicao foi escrita, nenhum audio de teste foi gravado, nenhum dialogo de teste foi anotado e nenhum numero foi medido — nem latencia, nem WER, nem acerto de extracao, nem acerto de intencao, nem nota de inteligibilidade. Este item tambem nao tem dono no roadmap do grupo. O que existe no repositorio hoje sao `print` soltos em `backend/main.py` e os relogios que a tela de chamada mostra na tira de etapas; nenhum dos dois grava numero em lugar nenhum. Este documento e a especificacao do que precisa ser construido.
Backlog: doc/backlog.md (MED-01). Requisitos: RNF01, RNF04, RIA01, RIA02, RIA03, RIA05, RIA06, RIA07, RIA08, RIA09.

## Objetivo

O documento oficial do projeto promete numero em nove requisitos (RNF01, RIA01, RIA02, RIA03, RIA05, RIA06, RIA07, RIA08 e RIA09) e nenhum deles foi medido. Sem medicao, as secoes de Resultados e de Testes do relatorio ficam vazias e a banca cobra exatamente isso: o grupo escreveu "WER de ate 15%" e nao tem como mostrar qual foi o WER.

O objetivo deste item e produzir esses numeros de um jeito que sobreviva a pergunta "como voces mediram?". Isso quer dizer tres coisas, nesta ordem: material de teste preparado antes (audios com transcricao de referencia, dialogos com o pedido esperado e a intencao rotulada), instrumento que produz o numero sem alguem digitar na mao, e registro do resultado junto com a data, a maquina e a versao do codigo. Numero sem esses tres pes nao entra no relatorio.

Este e, junto com o proprio pipeline, o maior risco da entrega. VOZ-01 e risco tecnico — pode nao ficar pronto. MED-01 e risco de nota mesmo com tudo pronto: pipeline funcionando e relatorio sem resultado ainda perde ponto.

## Usuarios e papeis

Item interno, sem usuario final. Quem usa:

| Quem | Para que |
| :-- | :-- |
| O time | gravar os audios, escrever as transcricoes de referencia, anotar os dialogos, rodar a medicao e avaliar a inteligibilidade da voz sintetizada (RIA08 exige avaliacao humana do grupo) |
| Quem escreve o relatorio | preencher as secoes de Resultados e de Testes com os numeros e a descricao do metodo |
| A professora e a banca | conferir se o numero declarado e reproduzivel a partir do que esta no repositorio |

RIA08 e o unico requisito da lista cujo numero sai de pessoa e nao de programa: a nota de inteligibilidade e opiniao do grupo, coletada numa escala. Os outros cinco saem de comparacao automatica entre o que o sistema produziu e o gabarito escrito antes.

## Pontos de entrada

O que existe hoje e pode servir de materia-prima:

| Caminho | O que e | Serve para |
| :-- | :-- | :-- |
| `backend/main.py`, ramo `tipo == "fim_da_fala"` | ponto onde o turno comeca a ser processado; hoje so tem `print` e o bloco `--- MOCK DA FASE 3 ---` | e onde o cronometro do turno tem que ser ligado (RNF01, RIA07) |
| `backend/main.py`, os `print` das rotas e do websocket | saida em texto no terminal do uvicorn | rastro de depuracao, nao medicao: nao tem tempo de etapa, nao tem numero de turno e nao vai para arquivo |
| `frontend/app.js`, `marcarEtapa` e `emSegundos` | fecham a etapa anterior da tira e escrevem quanto ela levou | leitura ao vivo, descartada quando a pagina recarrega |
| `frontend/app.js`, `tempoInicioTurno` e o elemento `tempo-turno` | tempo de parede do ultimo turno | leitura ao vivo; mede um intervalo diferente do RNF01, ver a subsecao de latencia |
| `frontend/app.js`, `escreverLog` | lista de log na tela, limitada por `LIMITE_LOG` e espelhada no `console.log` | acompanhar a chamada, nao registrar resultado |
| `backend/seed.py` | cardapio, clientes e historico com semente fixa (`SEMENTE = 10`) | base reproduzivel para escrever dialogo de teste e roteiro de CPF |
| `backend/repositorio.py` | unica porta de entrada do banco | conferir o que a extracao produziu contra o cardapio de verdade |

O que **nao existe** e precisa ser criado:

| Peca | Estado |
| :-- | :-- |
| Material de teste (audios, transcricoes de referencia, dialogos anotados, roteiros) | nao existe |
| Script que calcula WER | nao existe |
| Cronometragem por etapa no servidor e arquivo de log de latencia | nao existe |
| Script que compara pedido extraido com pedido esperado | nao existe |
| Ficha de coleta das notas de inteligibilidade | nao existe |
| Arquivo com os resultados consolidados | nao existe |
| Dependencia de medicao no `backend/requirements.txt` | nao existe: o arquivo tem `fastapi`, `uvicorn`, `python-multipart`, `sqlalchemy`, `psycopg[binary]` e `websockets`, e mais nada |
| Teste automatizado de qualquer tipo | nao existe: nao ha pasta de testes nem `pytest` no `requirements.txt` |

Qualquer pasta ou arquivo citado daqui para baixo e **proposta**, nao caminho existente. Nenhum deles esta no repositorio.

Nada disso roda sem o pipeline. `npm run dev` sobe o banco no Docker e o uvicorn na porta 3000 e a tela abre em `http://localhost:3000`, mas hoje a tela conecta, grava, manda os chunks e nao recebe resposta: nao ha transcricao, modelo de linguagem nem sintese para cronometrar.

## Telas

Nenhuma propria. A tela de chamada (ATD-01) ja mostra, na tira de etapas do topo, o tempo de cada etapa e o tempo de parede do ultimo turno no elemento `tempo-turno`. Isso e util na demonstracao e nao substitui a medicao: os numeros sao calculados no navegador com `Date.now()`, somem quando a pagina recarrega, nao vao para arquivo nenhum e dependem de o servidor mandar um frame `estado` por etapa. O `frontend/index.html` ainda imprime, ao lado desse numero, o texto "meta: 5 s" — meta que **nao foi definida nem medida** (ver Questoes em aberto).

A apresentacao dos resultados e tabela em markdown no repositorio e no relatorio, nao tela.

## Escopo

Oito medicoes, uma por subsecao. Todas dependem de VOZ-01 existir; nenhuma foi iniciada.

### WER da transcricao (nao iniciado)

**Requisito:** RIA01 — WER de ate 15% em audio limpo e ate 30% com ruido ambiente. O conjunto com ruido e tambem a unica evidencia numerica que sustenta o RNF04 (funcionamento estavel com ruido), que `doc/requisitos.md` lista com VOZ-01 e MED-01 juntos.

**Instrumento:** um script que recebe o par (transcricao de referencia, transcricao do faster-whisper) e devolve o WER. A formula e a distancia de edicao em nivel de palavra dividida pelo tamanho da referencia:

```text
WER = (S + D + I) / N
```

onde `S` e o numero de palavras substituidas, `D` o de palavras apagadas, `I` o de palavras inseridas pelo reconhecedor e `N` o numero de palavras da transcricao de referencia. O alinhamento entre as duas frases e o de Levenshtein aplicado a palavras, nao a letras. Exemplo: referencia "quero duas pizzas de calabresa" (N = 5) contra a saida "quero duas pizza de calabresa" da uma substituicao, WER = 1/5 = 20%. O WER pode passar de 100% quando o modelo insere muita palavra, e isso nao e erro de conta.

Duas armadilhas que precisam de regra escrita **antes** de medir, senao o numero muda conforme quem calcula:

1. **Normalizacao.** Referencia e saida passam pelo mesmo tratamento: minusculas, pontuacao removida, acento removido. Sem isso, "calabresa" e "Calabresa," contam como erro.
2. **Numero por extenso.** "2" e "dois" sao a mesma palavra falada e graficamente diferentes. Ou a referencia e escrita sempre por extenso e a saida e convertida, ou o contrario; o que nao pode e cada audio seguir um criterio. A regra escolhida vai escrita junto com o resultado.

Implementacao: biblioteca de WER (a `jiwer` e a usual) ou implementacao propria — a distancia de edicao por palavra sao umas trinta linhas. Nenhuma das duas esta no `requirements.txt` hoje; a escolha e de quem for implementar, e instalar dependencia nova passa pelo grupo.

**Material a preparar antes:** audios gravados pelo proprio time, com a transcricao de referencia escrita a mao ouvindo o audio — nunca corrigindo a saida do modelo, que e o jeito classico de fabricar um WER bom. Dois conjuntos:

| Conjunto | Como gravar | Serve a |
| :-- | :-- | :-- |
| Limpo | ambiente silencioso, microfone do notebook ou do fone, falando como quem faz um pedido de verdade | meta de 15% |
| Com ruido | as mesmas frases, com ruido de fundo controlado (televisao, conversa ao lado, ventilador), e o ruido descrito junto do arquivo | meta de 30% |

Cada frase gravada pelo mesmo falante nos dois conjuntos, para que a diferenca de WER seja do ruido e nao da voz. Vozes de integrantes diferentes, porque WER medido numa voz so nao diz nada sobre a proxima. As frases cobrem o que a conversa real tem: nome de produto do cardapio do seed, quantidade, CPF ditado digito a digito, endereco e forma de pagamento. Quantos audios e quantos falantes ainda nao foi definido (ver Questoes em aberto); o que ja da para dizer e que meia duzia de frases nao sustenta percentual nenhum.

**Registro:** uma linha por audio (arquivo, falante, conjunto, N, S, D, I, WER) e a media dos dois conjuntos no fim. A media e ponderada pelo total de palavras, nao a media aritmetica dos WERs por audio, senao a frase curta pesa igual a frase longa.

### Latencia por etapa e total (nao iniciado)

**Requisito:** RNF01 (latencia entre o fim da fala e o inicio da resposta em audio, meta a definir) e RIA07 (medir o tempo de cada etapa — transcricao, inferencia e sintese — de modo que a soma respeite a meta).

**Instrumento:** cronometragem dentro do servidor, com `time.perf_counter()` em volta de cada etapa, gravada em arquivo: uma linha por turno, em JSON, com um campo por etapa em milissegundos. `print` no terminal nao serve — o `npm run dev` sobe o uvicorn com `--log-level warning --no-access-log`, o terminal rola e nada fica guardado.

As etapas a cronometrar, na ordem do turno descrito em VOZ-01:

| Etapa | De onde ate onde |
| :-- | :-- |
| Decodificacao e fim de turno | do ultimo chunk de audio ate o turno ser fechado (pelo VAD ou pelo frame `fim_da_fala`) |
| Transcricao | entrada do PCM no faster-whisper ate o texto do turno |
| Inferencia | envio do prompt ao Llama 3.2 3B pelo Ollama ate a resposta completa |
| Sintese | entrada do texto no Piper ate o audio pronto |
| Envio | audio pronto ate o ultimo frame binario sair pelo websocket |

Os nomes das quatro etapas ja existem no protocolo (`estado` com `ouvindo`, `transcrevendo`, `pensando` e `respondendo`, tratados em `frontend/app.js`), e a cronometragem deve usar os mesmos recortes: numero medido e numero mostrado na tela tem que falar da mesma coisa.

**O numero do RNF01** e um recorte especifico: do fim da fala ate o **inicio** da resposta em audio. No protocolo atual isso vai do `fim_da_fala` (ou do fechamento do turno pelo VAD) ate o frame `audio_resposta` sair. Atencao a diferenca: a tela ja mostra o tempo de parede do turno no `tempo-turno`, mas ela cronometra de `fimDaFala` ate `voltarAOuvir`, que so acontece **depois que a resposta terminou de tocar** — ou seja, o numero da tela inclui a duracao do audio falado e e sempre maior que o do RNF01. A tira de etapas tambem mostra quanto cada etapa levou, so que medido no navegador a partir da chegada de cada frame `estado`: isso carrega rede e fila, nao separa carregamento de modelo de processamento e some no primeiro F5. Os dois numeros servem para demonstrar; nenhum deles substitui a cronometragem por etapa dentro do servidor, que e o que o RIA07 pede.

**Material a preparar antes:** os mesmos audios do WER, para que a latencia seja medida sobre entrada conhecida e repetivel, mais o registro da maquina alvo (processador, memoria, se tem GPU, sistema) e do tamanho de modelo usado em cada etapa. Numero de latencia sem a maquina anotada ao lado nao significa nada. A primeira execucao depois de subir o servidor carrega os modelos e e sempre a mais lenta: ela e medida e anotada em separado como "primeira chamada", e a meta e discutida sobre as seguintes.

**Registro:** arquivo de log com uma linha por turno, mais uma tabela consolidada com mediana e pior caso por etapa. Mediana, e nao so media: uma inferencia ruim no meio de vinte puxa a media e esconde o comportamento normal. O pior caso entra porque e ele que o cliente sente.

### Acerto da extracao do pedido (nao iniciado)

**Requisito:** RIA03 — pedido extraido de forma estruturada com acerto de no minimo 90% dos dialogos de teste, considerando itens e quantidades.

**Instrumento:** script que roda cada dialogo de teste pelo pipeline, pega o JSON de pedido que o modelo de linguagem produziu e compara com o pedido esperado, anotado a mao. A unidade de contagem e o **dialogo**, como o requisito diz: o dialogo conta como acerto so se o conjunto de itens e as quantidades baterem inteiros. Item a mais, item a menos ou quantidade trocada reprovam o dialogo. Junto disso vale contar tambem por item (quantos dos itens que apareceram sairam certos), porque e essa contagem que mostra onde o erro se concentra — mas o numero que responde ao RIA03 e o por dialogo.

A comparacao e feita sobre o produto ja resolvido contra o cardapio, com `buscar_produtos` de `backend/repositorio.py`: o esperado e escrito com o nome canonico do seed ("Coca-Cola 2 Litros") e o que o modelo falou ("coca cola") resolve para ele. O que nao resolve para nenhum produto conta como erro, nao como empate.

**Material a preparar antes:** um conjunto de dialogos de teste em arquivo, cada um com as falas do cliente na ordem e o pedido esperado anotado no formato que `salvar_pedido` aceita — lista de dicionarios com `produto`, `quantidade` e `observacao`, mais `endereco_entrega` e `forma_pagamento`. Os dialogos sao escritos em cima do cardapio do seed e precisam cobrir os casos que quebram, nao so os faceis:

| Tipo de dialogo | Por que precisa estar la |
| :-- | :-- |
| Pedido simples, um item | piso |
| Varios itens na mesma fala ("uma mussarela, uma coca e uma borda de catupiry") | e o caso normal e o que mais erra |
| Quantidade por extenso ("duas margherita") | a transcricao entrega texto, nao numero |
| Item citado sem o nome completo ("aquela de frango") | RIA06, contexto |
| Cliente altera o pedido no meio ("tira a coca, poe guarana") | RF09 |
| Produto fora do cardapio ("pizza de picanha") | RIA04: o esperado e o pedido **nao** ser gravado |
| Produto desativado ("escarola com bacon", `ativo = false` no seed) | mesma barreira, caso ja plantado em `backend/seed.py` |
| Nome ambiguo ("quero uma pizza") | o esperado e uma pergunta ao cliente, nao um sabor escolhido no chute |

Quantos dialogos ainda nao foi definido. Com dez dialogos, cada erro vale 10 pontos percentuais e a meta de 90% vira "pode errar um": e pouco para afirmar percentual, e isso precisa estar dito no relatorio em vez de escondido.

**Registro:** tabela com id do dialogo, pedido esperado, pedido obtido, acertou sim ou nao e o motivo do erro quando errou. O percentual final e dialogos certos sobre o total.

### Acerto da classificacao de intencao (nao iniciado)

**Requisito:** RIA05 — classificar corretamente a intencao em no minimo 90% dos casos, entre pedir item, tirar duvida, alterar, confirmar, cancelar e encerrar.

**Instrumento:** o mesmo script dos dialogos, lendo o campo de intencao que o modelo devolve e comparando com o rotulo escrito a mao. A unidade aqui e o **turno**, nao o dialogo: um dialogo de oito falas do cliente rende oito classificacoes. Alem do percentual global, o resultado sai como matriz de confusao 6 por 6 (esperado nas linhas, classificado nas colunas), porque o percentual sozinho esconde o que interessa: confundir "tirar duvida" com "pedir item" gera pedido errado, confundir "confirmar" com "encerrar" derruba a chamada antes de salvar.

**Material a preparar antes:** os mesmos dialogos da extracao, com cada fala do cliente rotulada com uma das seis intencoes. Duas regras para o rotulo nao virar acomodacao ao modelo:

- O rotulo e escrito **antes** de rodar o pipeline. Rotular depois de ver a saida transforma a medicao em concordancia consigo mesmo.
- Fala que carrega duas intencoes ("pode confirmar e ja fecha o pedido") ou e rotulada por uma regra fixa escrita no material (por exemplo, vale a intencao que decide a proxima acao), ou fica fora do conjunto. Nao pode ficar a criterio de quem confere no dia.

Ideal que duas pessoas rotulem separadamente e as divergencias sejam resolvidas antes da medicao; a divergencia entre humanos e um limite util para saber ate onde cobrar do modelo.

**Registro:** matriz de confusao, percentual global e a lista dos turnos errados com a fala inteira, que e o que orienta o ajuste do prompt.

### Confirmacao de dados criticos (nao iniciado)

**Requisito:** RIA02 — confirmacao verbal dos dados criticos reconhecidos por voz (CPF, quantidades, endereco e forma de pagamento), com acerto minimo de 95% **apos** a confirmacao.

**Instrumento:** execucao de um roteiro de chamada, com uma pessoa do time falando os dados e outra conferindo o que o sistema gravou contra o roteiro. O "apos a confirmacao" e o ponto central: o que se mede nao e se a transcricao acertou de primeira, e se o dado que **ficou valendo** depois de o atendente repetir e o cliente confirmar esta certo. Errar na primeira tentativa e corrigir na confirmacao conta como acerto; gravar errado depois de confirmado conta como erro. A unidade e o campo critico, nao a chamada: uma chamada com CPF, duas quantidades, endereco e forma de pagamento rende cinco campos.

Parte da barreira ja existe no codigo e nao precisa esperar o pipeline para ser exercitada: `cpf_valido` em `backend/seguranca.py` recusa CPF com digito verificador errado, e `interpretar_pagamento` e `salvar_pedido` em `backend/repositorio.py` levantam `ValueError` em quantidade quebrada e em pagamento ambiguo em vez de chutar. Isso reduz o erro que chega ao banco, mas nao e a medicao: o numero do RIA02 so sai com a fala no meio.

**Material a preparar antes:** um roteiro por execucao, escrito antes, com os quatro tipos de dado:

| Campo | Como preparar | Cuidado |
| :-- | :-- | :-- |
| CPF | usar os CPFs ficticios do `backend/seed.py`, gerados por `gerar_cpf` com digito verificador valido | **nunca usar CPF real de ninguem do grupo**: o roteiro fica versionado em texto puro e o banco so guarda o hash (`cliente.cpf_hash`), entao o CPF do teste vive no arquivo de teste |
| Quantidade | numeros falados por extenso e em digito, incluindo quantidade maior que dez | a quantidade quebrada ("meia pizza") entra como caso de borda: o esperado e recusar |
| Endereco | os enderecos dos clientes do seed, que tem rua, numero, complemento e bairro | endereco longo e onde a transcricao mais erra |
| Forma de pagamento | as quatro de `FORMAS_PAGAMENTO` mais as falas ambiguas ("no cartao", "na maquininha") | na ambigua o esperado e uma pergunta, nao um valor gravado |

**Registro:** tabela com execucao, campo, valor do roteiro, valor apos a confirmacao, acertou sim ou nao. O percentual e campos certos sobre campos totais, com contagem separada de "errou de primeira e a confirmacao corrigiu", que e o numero que mostra se a confirmacao esta fazendo o trabalho dela.

### Inteligibilidade e fator de tempo real da voz (nao iniciado)

**Requisito:** RIA08 — resposta sintetizada inteligivel, com nota media minima 4 em escala de 1 a 5 avaliada pelo grupo, e fator de tempo real inferior a 1.

**Instrumento:** duas medidas independentes.

1. **Inteligibilidade:** avaliacao humana. Um conjunto de frases sintetizadas pelo Piper e ouvido por integrantes do time, cada um dando nota de 1 a 5 (1 = nao da para entender, 5 = entendi tudo sem esforco). A nota que vale e a media de todas as notas de todos os avaliadores. Cada frase ouvida por pelo menos tres pessoas, e o que esta sendo julgado e a clareza do audio, nao se a frase e uma boa resposta de atendente.
2. **Fator de tempo real (RTF):** medida de programa, nao de gente. `RTF = tempo de sintese / duracao do audio gerado`. Sintetizar em 1,2 s uma frase que dura 4 s da RTF de 0,3, dentro da meta; RTF acima de 1 quer dizer que o sistema demora mais para produzir do que o audio dura, e a conversa nunca alcanca o tempo real. O tempo de sintese e o mesmo cronometro da etapa de sintese da subsecao de latencia; a duracao sai do proprio arquivo de audio gerado.

**Material a preparar antes:** uma lista de frases de atendente escritas antes, cobrindo o que o sistema realmente vai falar — cumprimento, leitura de item com preco, pergunta de confirmacao, repeticao de CPF digito a digito, repeticao de endereco e despedida. Numero falado, preco ("sessenta e seis reais e noventa") e CPF sao onde a sintese mais tropeca, e e justamente o que o cliente precisa entender. Junto disso, a ficha de coleta das notas, com uma coluna por avaliador. Quem escreveu a frase tambem pode avaliar, mas ninguem pode saber de antemao qual frase o grupo acha que e "a boa": as frases vao embaralhadas.

**Registro:** tabela com frase, nota de cada avaliador, media por frase, media geral, tempo de sintese, duracao do audio e RTF. Media geral abaixo de 4 nao vira arredondamento para cima: vira troca de voz ou de configuracao do Piper e nova medicao.

### Contexto da sessao ao longo dos turnos (nao iniciado)

**Requisito:** RIA06 — manter o contexto da sessao por no minimo dez turnos, permitindo que o cliente se refira a itens ja mencionados sem repeti-los. E requisito numerico (dez turnos), entao precisa de numero, e o numero sai daqui; a implementacao do contexto e de VOZ-01.

**Instrumento:** um dialogo de teste longo, escrito antes, com pelo menos doze turnos do cliente, em que os turnos do fim se referem a itens citados no comeco sem nomear o produto ("tira a cebola daquela primeira", "manda mais duas daquela que eu pedi no inicio"). O script dos dialogos de extracao serve aqui tambem; o que muda e o gabarito, que passa a dizer a qual item de qual turno cada referencia aponta. A contagem e binaria por referencia — resolveu para o item certo ou nao — e o numero que sai e o **indice do ultimo turno em que todas as referencias ainda foram resolvidas corretamente**. A meta do requisito e esse indice ser dez ou mais.

Duas regras para o numero nao sair generoso:

- A referencia tem que ser feita **sem** repetir o nome do produto. Se o cliente repete o nome, o turno testa extracao, nao contexto, e nao entra na contagem.
- Turno em que o modelo pede esclarecimento em vez de resolver conta como nao resolvido. Perguntar e melhor do que errar, mas nao e manter contexto.

**Material a preparar antes:** pelo menos tres dialogos de doze turnos ou mais, com o item alvo de cada referencia anotado ao lado da fala. Cada dialogo precisa ter mais de um item na mesa em algum momento, senao "aquela" so tem uma resposta possivel e a medicao nao mede nada.

**Registro:** por dialogo, a lista de turnos de referencia com resolvido sim ou nao, o indice do ultimo turno integro e quantos turnos a orquestracao estava enviando ao modelo na hora — e esse ajuste que muda o numero, entao ele tem que estar ao lado do resultado.

### Limiar de confianca para pedir repeticao (nao iniciado)

**Requisito:** RIA09 — pedir a repeticao da fala quando a confianca da transcricao ficar abaixo do limiar definido, em vez de assumir o conteudo reconhecido. O limiar **nao existe**: ninguem escolheu o numero, e escolher sem medir e chutar. A logica de pedir repeticao e de VOZ-01; o valor do limiar sai daqui.

**Instrumento:** o mesmo conjunto de audios do WER, rodado uma vez so. Para cada audio registra-se o par (medida de confianca que o transcritor devolveu, transcricao errada ou nao pelo criterio do WER). Com essa tabela, varre-se uma faixa de limiares e conta-se, para cada um, quantos audios corretos seriam mandados repetir (incomodo inutil) e quantos audios errados passariam adiante (o erro que o requisito quer evitar). O limiar escolhido e o ponto que o grupo aceitar nesse par, e ele vai escrito com os dois numeros ao lado, nunca sozinho.

**Cuidado que precisa estar dito:** qual e a medida de confianca depende do que o faster-whisper expuser quando for instalado. Ele nao esta no `backend/requirements.txt` e ninguem conferiu a saida dele ainda. A medicao so comeca depois que VOZ-01 disser qual e esse campo e se ele vem por segmento ou pela transcricao inteira; vindo por segmento, a regra de agregacao (menor confianca do turno, media ponderada pela duracao) tem que estar escrita **antes** de medir, senao o limiar muda conforme quem calcula.

**Material a preparar antes:** nenhum material novo — o conjunto do WER ja serve, desde que os audios com ruido estejam nele, porque e neles que a confianca baixa aparece.

**Registro:** tabela de limiar contra (repeticoes desnecessarias, erros que passaram), o limiar escolhido e a justificativa em uma linha. O valor escolhido volta para `doc/requisitos.md`, que hoje registra o RIA09 como "o limiar ainda nao foi definido".

## Dados

MED-01 **nao escreve nenhuma coluna do banco**. Nao existe tabela de metrica, de execucao de teste nem de resultado em `banco.sql`, e criar uma nao esta previsto (ver Questoes em aberto).

Le do banco, sempre pelas funcoes de `backend/repositorio.py`, e so para montar e conferir material de teste:

| Tabela | Colunas | Para que |
| :-- | :-- | :-- |
| `produto` | `nome`, `categoria`, `preco`, `ativo` | escrever dialogo com produto que existe, e com os que nao podem ser vendidos |
| `cliente` | `nome`, `telefone`, `endereco` | escrever o roteiro de endereco e de identificacao |
| `pedido`, `item_pedido` | `quantidade`, `preco_unitario`, `total` | conferir o que a extracao gravou contra o esperado |

A base da reproducao e o seed: `backend/seed.py` roda com semente fixa (`SEMENTE = 10`) e produz sempre o mesmo cardapio (19 produtos, 18 ativos), os mesmos 6 clientes e os mesmos 30 pedidos de historico. Por isso um dialogo de teste escrito hoje continua valendo na maquina de outro integrante, desde que ele tenha rodado `npm run seed`. Medicao feita em cima de banco populado na mao nao e reproduzivel e nao entra.

Fora do banco, MED-01 grava arquivos no repositorio: audios de teste, transcricoes de referencia, dialogos anotados, roteiros, log de latencia e as tabelas de resultado. Pasta, nome e formato desses arquivos ainda nao foram definidos.

## Acoes e regras

- **Nenhum numero entra no documento oficial sem estar reproduzivel a partir de material de teste versionado no repositorio.** Se a banca pedir "mostra como voces chegaram nesse 12%", a resposta tem que ser um comando e um arquivo, nao uma lembranca. Numero que so existe no print de uma conversa do grupo nao e resultado.
- **O gabarito e escrito antes da medicao.** Transcricao de referencia, pedido esperado e rotulo de intencao sao escritos ouvindo o audio e lendo o dialogo, nunca corrigindo a saida do sistema. Ajustar o gabarito depois de ver o resultado e fabricar o numero.
- **Toda medicao de tempo declara a maquina.** Processador, memoria, GPU se houver, sistema operacional e o tamanho de modelo de cada etapa vao junto do numero. Medicao de latencia feita em maquinas diferentes nao se soma nem se compara.
- **Medicao vale para uma versao do codigo.** O resultado anota o commit em que foi medido. Mudou o tamanho do modelo de transcricao ou o prompt, o numero anterior morreu e a medicao se repete.
- **Onde nao houve medicao, a palavra e "a medir".** Nao existe estimativa, "cerca de", "aproximadamente" nem numero de referencia da internet apresentado como resultado do grupo. Numero de terceiro, se aparecer, vem com a fonte e com a etiqueta de que nao e medicao nossa.
- **Falha tambem e resultado.** WER de 38% com ruido e um numero legitimo: vai para o relatorio com a analise do porque e com o que seria feito para melhorar. Esconder a medicao ruim e o jeito mais garantido de a banca achar o problema.
- **O que a tela mostra nao e a medicao.** Os tempos da tira de etapas e o `tempo-turno` sao apoio de demonstracao; o numero do relatorio sai do log do servidor.
- **CPF de teste e sempre ficticio**, gerado como em `backend/seed.py`. O roteiro fica em texto puro no repositorio; CPF real de integrante nao entra nunca.
- **Quem avalia inteligibilidade nao avalia sozinho.** A nota do RIA08 sai de pelo menos tres avaliadores por frase, com as frases embaralhadas.

## Casos de borda

| Situacao | Como tratar |
| :-- | :-- |
| Transcricao sai vazia | WER = 100% naquele audio (todas as palavras da referencia contam como apagadas). Nao e descartado do conjunto: audio que o modelo nao transcreveu e exatamente o caso que a meta precisa enxergar |
| Referencia com digito ("2") e saida por extenso ("dois"), ou o contrario | Resolvido pela regra de normalizacao escrita antes. O que nao pode e decidir caso a caso |
| Audio em que ninguem do grupo concorda com o que foi dito | Fora do conjunto, com o motivo anotado. Referencia duvidosa contamina o WER e nao tem como ser defendida na banca |
| Primeira chamada depois de subir o servidor | Carrega os modelos e e sempre a mais lenta. Medida e anotada em separado como "primeira chamada"; a meta do RNF01 e discutida sobre as chamadas seguintes |
| Etapas que se sobrepoem (transcricao ainda rodando enquanto chega audio) | O tempo total do turno nao e a soma das etapas. Registrar total e etapas em campos separados e nunca reconstruir o total somando |
| Outro programa pesado aberto durante a medicao | Invalida a rodada. Medicao de latencia com o navegador cheio de aba, com o Docker fazendo build ou com modelo baixando nao serve |
| Dialogo em que o esperado e o sistema **recusar** (produto inexistente, desativado, quantidade quebrada) | Acerto e recusar. Se o pedido for gravado assim mesmo, e erro grave: conta como dialogo errado e vai citado a parte, porque fere o RIA04 |
| Dialogo em que o esperado e uma **pergunta** ("quero uma pizza") | Acerto e perguntar qual sabor. Escolher um sozinho conta como erro, mesmo que o sabor escolhido fosse plausivel |
| Fala com duas intencoes | Regra fixa escrita no material de teste, ou a fala fica fora do conjunto |
| Dado critico que o cliente corrige na confirmacao | Conta como acerto (o requisito e "apos a confirmacao"), e a correcao e contada em coluna separada |
| Cliente confirma um dado que estava errado | Erro, e dos graves: e o caso que o RIA02 existe para evitar |
| Nota de inteligibilidade dada por quem escreveu a frase | Permitido, com as frases embaralhadas e pelo menos tres avaliadores. Uma pessoa so avaliando nao produz numero |
| RTF calculado sobre uma frase de meio segundo | Nao serve: o custo fixo de carregar o modelo domina. A lista usa frases do tamanho das que o atendente fala de verdade |
| VOZ-01 cair para o caminho de contingencia (transcrever o turno inteiro no `fim_da_fala`, sem transcricao incremental) | A medicao continua valendo e os numeros de latencia mudam de significado: o tempo de transcricao passa a comecar so no fim da fala. Isso vai anotado junto do resultado, porque muda a leitura do RNF01 |
| Medicao feita antes de `npm run seed` | Resultado invalido: o dialogo de teste referencia produto que nao existe naquele banco |

## Fora de escopo

- Implementar transcricao, modelo de linguagem, sintese, VAD e orquestracao: VOZ-01. MED-01 mede o que VOZ-01 entregar, e depende de VOZ-01 expor o tempo de cada etapa (RIA07).
- Validacao de item contra o cardapio e gravacao do pedido: PED-01. MED-01 mede o acerto, nao implementa a barreira.
- Protocolo do websocket e frames de estado: PRO-01. MED-01 usa os frames que existirem, nao define frame novo.
- Tira de etapas, relogios da tela e resumo da chamada: ATD-01.
- Implementar o contexto de sessao (RIA06) e a logica que pede repeticao abaixo do limiar (RIA09): a implementacao e de VOZ-01. A **medicao** dos dois passou a ser deste item — sao requisitos numericos (dez turnos, limiar) e estavam sem dono —, e cada um tem sua subsecao em Escopo.
- RIA04 (produto inexistente) e contado dentro da medicao de extracao, como caso que o sistema tem que recusar; a implementacao da recusa e de PED-01 e ja existe.
- Teste unitario e de integracao do codigo que ja esta pronto (`repositorio.py`, `seguranca.py`, `models.py`). Nao existe nenhum teste automatizado no repositorio e cria-los nao esta previsto neste item — o que nao quer dizer que nao fariam falta.
- Teste de carga, varias chamadas simultaneas e medicao de consumo de memoria ou de CPU: nao foi pensado nem testado, e o escopo do semestre e uma chamada por vez.
- Comparacao entre modelos (Whisper `tiny` contra `small`, Llama contra outro modelo) como estudo. O que MED-01 preve e medir a configuracao escolhida; se o grupo quiser comparar tamanhos para escolher, e uma rodada de medicao extra e precisa de tempo no cronograma.
- Medicao em celular ou em telefonia real: fora do semestre. O escopo e chamada simulada, em desktop.

## Questoes em aberto

**Quem do grupo assume MED-01?** Hoje ninguem. O item nao tem dono, e e o unico que produz o conteudo das secoes de Resultados e de Testes do relatorio. Enquanto nao tiver dono, ele nao acontece: cada integrante esta ocupado com o proprio pedaco do pipeline, e medicao e sempre o que fica para depois.
Recomendacao: nomear um responsavel unico agora, na proxima reuniao, e nao deixar a medicao com quem esta implementando o pipeline, porque sao as duas frentes que mais competem por tempo no fim do semestre. O responsavel nao precisa ser quem mais programa: boa parte do trabalho e preparar material e conferir gabarito. A coleta das notas de inteligibilidade (RIA08) envolve o time inteiro de qualquer forma e pode ser feita numa reuniao so.

**Quando isso entra no cronograma?** MED-01 e o ultimo da ordem de ataque do `doc/backlog.md` porque so se mede o que existe, mas "ultimo" nao pode virar "na semana da entrega". A preparacao do material — gravar audios, escrever transcricoes de referencia, anotar dialogos e rotular intencao — **nao depende do pipeline** e pode comecar hoje.
Recomendacao: separar em duas janelas. A preparacao do material comeca em paralelo com VOZ-01, assim que o dono for definido, porque e trabalho de leitura e escrita. A medicao propriamente dita roda depois da primeira versao ponta a ponta do pipeline e antes da entrega, com folga de pelo menos duas semanas: tempo de medir, achar resultado ruim, ajustar e medir de novo. Medicao que so cabe uma vez no calendario e medicao que nao pode dar errado, e sempre da.

**Qual e a meta de latencia do RNF01?** O requisito diz que a meta sera definida apos teste real no hardware alvo, nada foi medido e a meta nao existe. Enquanto isso, o `frontend/index.html` ja imprime "meta: 5 s" ao lado do tempo do turno — um numero que ninguem decidiu, numa tela que a banca vai ver.
Recomendacao: medir o piso primeiro (transcricao, inferencia e sintese isoladas, com o modelo menor de cada etapa na maquina alvo) e so entao fixar a meta com folga, registrando a decisao em `doc/requisitos.md`. Ate la, ou o texto da tela troca para algo sem numero ("meta a definir"), ou o grupo assume os 5 s como meta declarada e mede contra ela. O que nao da e chegar na banca com um numero na tela que nao esta em documento nenhum.

**Qual e a maquina alvo?** A mesma pergunta aparece em VOZ-01, e sem resposta nenhum numero de latencia significa coisa alguma: o mesmo pipeline entrega tempos completamente diferentes em maquinas diferentes.
Recomendacao: eleger uma maquina unica como alvo oficial, registrar a ficha dela (processador, memoria, GPU, sistema) junto dos resultados de MED-01 e rodar toda medicao de tempo nela. As outras maquinas continuam servindo para desenvolver e para gravar audio.

**Qual o tamanho de cada conjunto de teste?** Quantos audios para o WER, quantos dialogos para extracao e intencao, quantas execucoes de roteiro para os dados criticos, quantas frases para a inteligibilidade. Nada disso esta definido, e o tamanho decide se o percentual quer dizer alguma coisa: com dez dialogos, a meta de 90% e "errar no maximo um".
Recomendacao: fixar os numeros junto com o dono do item — como piso, 20 audios por conjunto (limpo e com ruido) com pelo menos tres falantes diferentes, 20 dialogos de teste e 10 frases de sintese. Se o tempo nao permitir, medir com menos e **declarar o tamanho da amostra ao lado do percentual** no relatorio, em vez de apresentar percentual de amostra pequena como se fosse solido.

**Onde o material de teste fica guardado?** Audio e arquivo binario e o repositorio e de codigo; dezenas de gravacoes incham o clone de todo mundo. Nenhuma pasta foi criada e nenhum formato foi decidido.
Recomendacao: criar uma pasta unica no repositorio para o material de teste, com os audios em formato comprimido e curtos (uma frase por arquivo) e as transcricoes, dialogos e resultados em texto (markdown ou JSON) ao lado deles. Se o volume incomodar, a alternativa e manter so transcricoes e resultados no repositorio e os audios numa pasta compartilhada do grupo, com o link registrado — pior para a reproducao, mas melhor do que nao gravar audio nenhum.

**Os resultados vao para o banco ou para arquivo?** Nao existe tabela de metrica em `banco.sql` e este item nao preve criar uma.
Recomendacao: manter em arquivo. Criar tabela de metrica no banco do projeto mistura dado de negocio com dado de experimento, e o relatorio precisa de tabela em markdown, nao de consulta SQL. Log de latencia em JSON por turno mais tabelas consolidadas em markdown resolvem o que a banca vai pedir.
