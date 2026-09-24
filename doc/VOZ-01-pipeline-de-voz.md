# VOZ-01 Pipeline de voz

Status: nao iniciado — nenhuma linha de transcricao, modelo de linguagem, sintese, deteccao de atividade de voz ou orquestracao foi escrita; este documento e a especificacao do que precisa ser construido, e as unicas pecas que existem hoje sao o tunel de audio do `/ws/falar` (que grava os chunks em disco) e o acesso ao banco do `backend/repositorio.py`.
Backlog: doc/backlog.md (VOZ-01). Requisitos: RF02, RF06, RF10, RNF01, RNF02, RNF04, RIA01, RIA05, RIA06, RIA09.

## Objetivo

Transformar o audio que chega pelo WebSocket em uma conversa: transcrever a fala do cliente enquanto ele fala, entender o que ele quis dizer sem perder o fio do dialogo, decidir a proxima frase do atendente e devolver essa frase em voz. Hoje o servidor recebe os bytes e os joga num arquivo; nada os le. Este item e a camada que falta entre o transporte (PRO-01) e o banco (PED-01, CLI-01), e e a parte de maior risco tecnico do projeto, porque exige transcricao incremental sobre um fluxo de audio de navegador e uma decisao confiavel de quando a frase do cliente terminou.

## Usuarios e papeis

Item interno: nenhum usuario final usa VOZ-01 diretamente. Quem consome e o handler do WebSocket, e o cliente so percebe o resultado pela tela de chamada (ATD-01) e pela voz que sai do alto-falante.

## Pontos de entrada

O que existe hoje:

| Caminho | O que e | Estado |
| :-- | :-- | :-- |
| `backend/main.py`, rota `@app.websocket("/ws/falar")` | Recebe os chunks binarios e os frames de controle de texto | Pronto como tunel, sem pipeline |
| `backend/main.py`, ramo `tipo == "iniciar_chamada"` | Le `controle.get("formato")` e guarda em `formato_do_audio` | Pronto; a variavel ainda nao e usada por ninguem |
| `backend/main.py`, ramo `tipo == "fim_da_fala"` | Ponto exato onde a transcricao do turno tem que ser chamada; hoje so tem `print` e um bloco de comentario `--- MOCK DA FASE 3 ---` | Marcado, nao implementado |
| `backend/main.py`, linha comentada `await websocket.send_json({"tipo": "pronto", "versao": 1})` | Comentada de proposito: o servidor so se apresenta quando houver transcricao de verdade | Aguardando VOZ-01 |
| `backend/main.py`, `caminho_audio = "audio_cliente_streaming.webm"` | Arquivo unico onde todos os chunks sao concatenados | Pronto, e provisorio |
| `backend/repositorio.py` | Unica porta de entrada do banco; e por aqui que o pipeline consulta cardapio e historico | Pronto e testado |
| `POST /api/v1/falar` em `backend/main.py` | Recebe um arquivo de audio inteiro e devolve o mesmo arquivo de volta | Eco, sem pipeline; serve de rota de teste sem WebSocket |

O que nao existe e precisa ser criado: os modulos de transcricao, de modelo de linguagem, de sintese e de orquestracao. Nenhum arquivo desses existe no repositorio hoje, e os nomes serao definidos quando o codigo for escrito.

```bash
npm run dev
```

Sobe o Postgres no Docker e o uvicorn na porta 3000. A tela fica na raiz, `http://localhost:3000`, e o WebSocket em `/ws/falar`.

Dependencias de execucao: `backend/requirements.txt` hoje tem `fastapi`, `uvicorn`, `python-multipart`, `sqlalchemy`, `psycopg[binary]` e `websockets`. Nao tem faster-whisper, nao tem cliente de Ollama e nao tem Piper — nada disso foi instalado ainda.

## Telas

Nenhuma propria. O efeito de VOZ-01 aparece na tela de chamada (ATD-01), que mostra transcricao, estado do turno e o pedido em construcao. O que trafega entre servidor e tela e o protocolo de PRO-01.

## Escopo

### Transcricao (nao iniciado)

Implementacao escolhida: **faster-whisper**, que e o Whisper reimplementado sobre o runtime CTranslate2, com os pesos quantizados em 8 bits.

| | |
| :-- | :-- |
| Entra | Audio do cliente em PCM mono, com taxa de amostragem fixa (o Whisper trabalha em 16 kHz), vindo do decodificador continuo descrito em "Streaming e fim de fala" |
| Sai | Texto do turno, mais o idioma detectado e a medida de confianca que o modelo devolve por segmento |
| Atende | RF02 (transcrever em tempo real), RIA01 (WER), RIA09 (confianca baixa) |

Por que faster-whisper e nao a implementacao original em PyTorch: os pesos sao os mesmos e a qualidade da transcricao e a mesma, mas o CTranslate2 roda o modelo com muito menos memoria, e a quantizacao de 8 bits torna viavel rodar em CPU — que e o cenario provavel das maquinas do time. Como o projeto tem que rodar inteiro na maquina local e sem custo de API (RNF02), essa e a diferenca que decide.

O tamanho do modelo (`tiny`, `base`, `small`, `medium`) ainda nao foi escolhido: e a troca direta entre WER (RIA01) e latencia (RNF01), e so o teste no hardware alvo resolve. Ver "Questoes em aberto".

A confianca por segmento e o que alimenta RIA09: abaixo do limiar, o atendente pede para o cliente repetir em vez de assumir o que ouviu. O limiar nao foi definido — a medir, em MED-01.

### Modelo de linguagem (nao iniciado)

**Llama 3.2 3B** servido pelo **Ollama**, rodando na propria maquina.

O papel dele, em tres frentes:

1. **Manter o contexto da sessao.** O cliente diz "quero duas daquelas" tres turnos depois de citar a margherita; o modelo tem que saber a qual item ele se refere. RIA06 exige no minimo dez turnos de contexto.
2. **Saber o que ainda falta no pedido.** Itens, quantidades, endereco de entrega e forma de pagamento sao os campos que o pedido precisa; o modelo compara o que ja tem com o que falta e formula a proxima pergunta. Quem grava e `salvar_pedido`, que recusa pedido sem nenhum item.
3. **Formular a resposta em texto**, que segue para a sintese.

Engenharia de prompt: o prompt de sistema carrega o cardapio vindo do banco (`listar_cardapio` em `backend/repositorio.py`), as regras de atendimento e as formas de pagamento aceitas, que sao exatamente as quatro de `FORMAS_PAGAMENTO`: `pix`, `dinheiro`, `cartao_credito` e `cartao_debito`. Colocar o cardapio no prompt reduz a invencao de produto, mas **nao** a elimina — quem elimina e a validacao contra o banco, no PED-01.

Saida estruturada: alem da frase falada, o modelo devolve o estado do pedido em JSON, e esse JSON tem que casar com a assinatura que ja existe no repositorio:

```python
salvar_pedido(db, cliente_id, itens, endereco_entrega=None, forma_pagamento=None)
```

Cada elemento de `itens` e um dicionario lido pelas chaves `produto`, `quantidade` e `observacao` — a descricao completa de cada campo, do que cada um aceita e do que faz a gravacao falhar esta em PED-01. Duas consequencias praticas para o prompt: `quantidade` tem que ser inteiro (quantidade quebrada levanta `ValueError` de proposito, porque meia pizza nao existe no cardapio) e o texto de `produto` e comparado com o cardapio ja normalizado, sem acento e sem hifen, entao "coca cola" resolve para "Coca-Cola 2 Litros" sem o modelo precisar acertar a grafia.

A classificacao de intencao (RIA05: pedir item, tirar duvida, alterar, confirmar, cancelar e encerrar) sai do mesmo JSON. Se vira um campo do proprio JSON de estado ou uma chamada separada ao modelo e decisao da implementacao; a segunda opcao custa uma inferencia a mais por turno e pesa em RNF01.

### Sintese (nao iniciado)

**Piper**, arquitetura **VITS** ponta a ponta: um unico modelo vai do texto a forma de onda, sem o passo intermediario de espectrograma mais vocoder que as pilhas classicas usam. E o que permite sintetizar em CPU com fator de tempo real baixo, exigencia do RIA08.

| | |
| :-- | :-- |
| Entra | A frase do atendente, em texto, vinda do modelo de linguagem |
| Sai | Audio, que o servidor manda para a tela pelo frame de audio da resposta, definido em PRO-01 |

A voz em portugues do Brasil ainda nao foi escolhida, e o formato do audio devolvido tambem nao esta fechado — quem fecha e PRO-01, porque depende do que a tela consegue tocar. RIA08 cobra nota media minima 4 de inteligibilidade avaliada pelo grupo: nao foi avaliado, a medir em MED-01.

### Streaming e fim de fala (nao iniciado)

Este e o problema central e o mais dificil do projeto.

O navegador grava com `MediaRecorder` e entrega pedacos de container WebM. **Um chunk isolado de WebM nao e decodificavel sozinho**: o cabecalho do container vai no primeiro pedaco e os seguintes sao continuacao dele. Quem tenta abrir o pedaco 7 como se fosse um arquivo recebe lixo. Decodificavel e o arquivo acumulado — e e exatamente isso que `backend/main.py` faz hoje, escrevendo tudo em `audio_cliente_streaming.webm` com o arquivo aberto do inicio ao fim da conexao.

Isso funciona para guardar, mas nao para transcrever a medida que o cliente fala (RF02). Transcricao incremental exige um **decodificador continuo alimentado pelo fluxo**: um processo que recebe os bytes do WebM na ordem em que chegam, sem nunca fechar a entrada, e emite PCM 16 kHz mono conforme decodifica. O pipeline le esse PCM e passa janelas dele para a transcricao. Reabrir o arquivo inteiro a cada chunk e a alternativa ingenua e nao escala: o custo cresce com a duracao da chamada.

A segunda metade do problema e saber **quando a frase terminou**. Hoje quem decide e a tela, que manda o frame de controle `fim_da_fala`, tratado em `backend/main.py`. Para conversa natural e para aguentar ruido de fundo (RNF04), o servidor precisa de **deteccao de atividade de voz** sobre o PCM: distinguir fala de silencio e de ruido, e fechar o turno depois de um intervalo de silencio. A biblioteca de VAD ainda nao foi escolhida e nada foi instalado. O `fim_da_fala` da tela continua valendo como comando explicito e como caminho de reserva, seja qual for a decisao.

Risco assumido e registrado aqui: se a transcricao incremental nao fechar a tempo no semestre, o caminho de contingencia e transcrever o turno inteiro ao receber `fim_da_fala`. Isso cumpre RF06, RF10 e a conversa ponta a ponta, mas **nao** cumpre RF02 no sentido estrito de "a medida que ele fala". Cair para esse caminho e decisao do grupo e tem que ser declarado na banca, nao escondido.

### Orquestracao (nao iniciado)

A sequencia de um turno, quando existir:

```text
chunk de audio  -> decodificador continuo -> PCM
PCM             -> VAD -> fim do turno (ou frame fim_da_fala vindo da tela)
PCM do turno    -> faster-whisper -> texto + confianca
  confianca baixa -> pede repeticao (RIA09) e o turno termina aqui
texto           -> Llama 3.2 3B pelo Ollama, com cardapio e historico no prompt
                -> frase do atendente + estado do pedido em JSON
itens do JSON   -> validacao contra o cardapio (PED-01)
frase           -> Piper -> audio
audio + estado  -> frames do protocolo (PRO-01) -> tela
```

Onde encosta nos outros itens:

| Fronteira | Quem manda |
| :-- | :-- |
| Formato dos frames, nomes dos campos, ordem das mensagens, quem fala primeiro | PRO-01 |
| Validacao de item contra o cardapio, montagem e gravacao do pedido, forma de pagamento | PED-01 e `backend/repositorio.py` |
| CPF, identificacao e cadastro do cliente no meio da conversa | CLI-01 e `backend/seguranca.py` |
| Tabelas, colunas e sessao do banco | DAD-01 |
| Medicao de latencia por etapa, WER e acerto de intencao | MED-01 |

O modelo de linguagem nunca fala com o banco direto. Toda consulta passa pelas funcoes de `backend/repositorio.py`, que ja existem: `listar_cardapio`, `buscar_produtos`, `buscar_produto`, `historico_cliente`, `itens_mais_pedidos_do_cliente` e `itens_mais_pedidos_da_casa`.

## Dados

Le, pelo `backend/repositorio.py`, com a sessao aberta pelo `get_db` de `backend/database.py`:

| Tabela | Colunas lidas | Para que |
| :-- | :-- | :-- |
| `produto` | `id`, `nome`, `descricao`, `categoria`, `preco`, `ativo` | Montar o cardapio do prompt e responder duvida de preco |
| `pedido` | `id`, `cliente_id`, `criado_em` | Historico do cliente no prompt |
| `item_pedido` | `produto_id`, `quantidade` | Item mais pedido, base da recomendacao |
| `cliente` | `id`, `nome`, `endereco` | Chamar o cliente pelo nome e sugerir o endereco de sempre |

Escreve: **nenhuma coluna, diretamente**. VOZ-01 nao faz INSERT nem UPDATE. Quem grava pedido e item e `salvar_pedido` (PED-01); quem grava cliente e `criar_cliente` (CLI-01). VOZ-01 so entrega os dados estruturados para essas funcoes.

Fora do banco, escreve em disco o audio da chamada — hoje `audio_cliente_streaming.webm`, na pasta de onde o uvicorn foi iniciado, um arquivo unico sobrescrito a cada conexao. Politica de nome, de pasta e de descarte desse arquivo nao esta definida.

## Acoes e regras

- **Nada sai da maquina** (RNF02). Transcricao, modelo de linguagem e sintese rodam localmente; o audio e o texto do cliente nao vao para nenhuma API externa e nenhum servico pago entra no caminho. Qualquer dependencia que faca chamada de rede para fora esta vetada neste item.
- **Todo item extraido pelo modelo passa pela validacao do cardapio** antes de entrar no pedido (RIA04). A validacao nao e feita aqui: e feita em `salvar_pedido` e `buscar_produtos`, no PED-01. VOZ-01 nao pode montar item por conta propria, e produto que o modelo inventou tem que derrubar a gravacao em vez de ser gravado.
- **Nome ambiguo nao vira escolha do codigo.** `buscar_produto` devolve `None` quando a fala casa com mais de um produto, e `salvar_pedido` levanta `ValueError` listando os candidatos. O comportamento certo do pipeline e transformar isso em pergunta ao cliente.
- **Confianca baixa na transcricao vira pedido de repeticao** (RIA09). Abaixo do limiar, o atendente pede para repetir; assumir o texto reconhecido esta proibido. Vale com forca dobrada para CPF, quantidade, endereco e forma de pagamento (RIA02).
- **Dado critico reconhecido por voz e confirmado em voz** antes de ser usado (RIA02): CPF, quantidades, endereco e forma de pagamento.
- **O servidor so manda o frame de apresentacao** quando a transcricao existir de verdade. A linha esta comentada em `backend/main.py` de proposito: mandar antes faz a tela esperar por uma transcricao que nunca chega.
- **O contexto da sessao vive no servidor**, por conexao, e morre quando a conexao cai. Nao ha persistencia de dialogo em banco.
- **Uma sessao nao ve o contexto da outra.** Duas chamadas simultaneas nao podem compartilhar estado de conversa.

## Casos de borda

| Situacao | Comportamento esperado |
| :-- | :-- |
| Chunk de audio chega antes do `iniciar_chamada`, sem formato declarado | O decodificador ainda nao sabe o que abrir; tratar como erro de protocolo e nao adivinhar o container. Hoje `formato_do_audio` nasce `None` e ninguem le essa variavel |
| Navegador grava em formato diferente do esperado (mp4, ogg) | O formato vem declarado no `iniciar_chamada` e o decodificador tem que respeita-lo; formato nao suportado vira erro explicito, nao transcricao vazia |
| Cliente fica calado o turno inteiro | O VAD nao fecha turno; passado o tempo limite, o atendente pergunta se o cliente ainda esta na linha. Tempo limite nao definido |
| Ruido ambiente alto, sem fala (RNF04) | O VAD nao pode tratar ruido como fala e abrir turno vazio; se a transcricao sair com confianca baixa, cai em RIA09 |
| Transcricao sai vazia ou so com pontuacao | Nao chama o modelo de linguagem; pede repeticao |
| Cliente fala por cima da resposta do atendente | Nao resolvido. O protocolo atual espera a tela avisar que a resposta terminou de tocar antes do proximo turno. Interrupcao esta fora de escopo neste semestre |
| Ollama nao esta rodando ou o modelo nao foi baixado | Erro explicito para a tela e mensagem clara no log; nao pode virar silencio |
| Modelo devolve JSON malformado ou fora do formato | Nao grava nada. Uma nova tentativa e, se falhar de novo, o atendente pergunta outra vez em linguagem natural |
| Modelo cita produto que nao esta no cardapio, ou que esta com `ativo` em falso | `salvar_pedido` levanta `ValueError` e o pedido inteiro nao entra no banco. O seed mantem a "Pizza de Escarola com Bacon" desativada exatamente como caso de teste disso |
| Conexao cai no meio do turno | O contexto da sessao se perde. Nao ha retomada de conversa; o cliente recomeca |
| Latencia estoura a meta do RNF01 | Nao ha degradacao automatica implementada nem meta definida. A medir em MED-01 |

## Fora de escopo

- Captura do audio no navegador, permissao de microfone e reproducao da resposta: ATD-01.
- Formato dos frames, ordem das mensagens e versionamento do protocolo: PRO-01.
- Validacao de item, calculo do total e gravacao do pedido: PED-01.
- CPF, hash, identificacao e cadastro do cliente: CLI-01.
- Esquema do banco e sessao: DAD-01.
- Medicao de WER, de latencia por etapa e de acerto de intencao: MED-01. VOZ-01 precisa expor o tempo de cada etapa para que MED-01 consiga medir (RIA07), mas a medicao em si nao e daqui.
- Telefonia real, chamada por linha telefonica e aplicativo de celular: fora do semestre. O escopo e chamada simulada, no navegador, em desktop.
- Interrupcao do atendente pela fala do cliente.
- Varias chamadas simultaneas com garantia de desempenho: nao foi pensado nem testado.

## Questoes em aberto

**Qual maquina e o hardware alvo?** O pipeline inteiro (Whisper, Llama 3.2 3B e Piper na mesma maquina, junto com o Postgres) muda de viabilidade conforme a maquina. Nao esta definido se o alvo e o notebook de um integrante especifico, a maquina do laboratorio ou "qualquer maquina do time".
Recomendacao: eleger uma maquina unica como alvo oficial, registrar processador, memoria e placa de video em MED-01 e rodar toda medicao nela. Sem alvo fixo, nenhum numero de latencia significa coisa alguma e o RNF01 nao tem como ser fechado.

**Qual a meta de latencia do RNF01?** O proprio requisito diz que a meta sera definida apos teste real no hardware alvo. Nada foi medido, entao nao ha meta.
Recomendacao: medir primeiro o piso — transcricao, inferencia e sintese isoladas, com o modelo menor de cada etapa — e so entao fixar a meta em cima do que a maquina entrega, com folga. Fixar numero antes de medir e escolher um numero para nao cumprir.

**Roda em CPU ou em GPU?** Afeta o tamanho do modelo de transcricao, o tempo de inferencia do Llama e o custo de instalacao na maquina de cada integrante.
Recomendacao: assumir CPU como piso obrigatorio, porque e o que garante que todo mundo do time consegue rodar, e tratar GPU como aceleracao opcional na maquina alvo. Se a medicao mostrar que a CPU nao alcanca a meta, a decisao passa a ser do grupo com a professora: baixar o tamanho do modelo de transcricao ou exigir GPU na apresentacao.
