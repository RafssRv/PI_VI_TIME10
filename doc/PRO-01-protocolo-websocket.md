# PRO-01 Protocolo do WebSocket

Status: Parcial. O contrato esta definido e implementado inteiro do lado da tela (`frontend/app.js`), e o servidor ja aceita os frames de texto sem cair (`backend/main.py`, `websocket_audio`); o que falta e o servidor ter o que responder. Das nove mensagens de servidor para tela, nenhuma e enviada hoje, porque o pipeline que produziria transcricao, audio e pedido nao existe (VOZ-01). Na pratica a conexao de hoje e um tunel de audio de mao unica: a tela sobe os pedacos e o servidor grava tudo em disco.

Backlog: doc/backlog.md (PRO-01). Requisitos: RF01. RF02, RF10 e RF11 dependem deste protocolo para chegar ate a tela, mas o codigo que os cumpre e de VOZ-01 e PED-01.

## Objetivo

Definir o que trafega no WebSocket `/ws/falar`: quais frames existem, quem fala primeiro, o nome de cada campo e o efeito de cada mensagem dos dois lados. Este item nao transcreve, nao pensa e nao sintetiza nada; ele e o cano por onde tudo isso passa. Quem for implementar a orquestracao (VOZ-01) escreve o servidor contra este documento, sem ter que ler o JavaScript da tela.

O protocolo tambem resolve um problema de cronograma: a tela ja esta escrita e o servidor ainda nao. Por isso ele nasce com um aperto de mao em que a tela fica calada ate o servidor se apresentar, o que deixa os dois lados evoluirem sem quebrar um ao outro.

## Usuarios e papeis

Item interno, sem usuario final direto. Quem le e quem implementa a orquestracao do pipeline (VOZ-01) e quem mexe na tela de chamada (ATD-01). O cliente da pizzaria so ve o efeito: a etapa acesa na tira do topo, a transcricao aparecendo, a comanda se enchendo e a voz do atendente tocando.

## Pontos de entrada

| Caminho | O que e | Estado |
|---|---|---|
| `backend/main.py`, `@app.websocket("/ws/falar")` -> `websocket_audio` | Aceita a conexao, le os frames e trata quatro dos cinco controles da tela | Tunel pronto, sem pipeline |
| `backend/main.py`, linha 75 (comentada): `await websocket.send_json({"tipo": "pronto", "versao": 1})` | O aperto de mao. Comentada de proposito | Aguardando VOZ-01 |
| `backend/main.py`, ramo `tipo == "fim_da_fala"` (bloco `--- MOCK DA FASE 3 ---`) | Onde a transcricao do turno tem que ser chamada | Marcado, nao implementado |
| `frontend/app.js`, cabecalho (linhas 1 a 58) | O contrato publicado, mensagem por mensagem | Pronto |
| `frontend/app.js`, `conectar`, `tratarMensagem`, `aplicarMensagem`, `aplicarEtapa`, `enviarTexto` | A implementacao do lado da tela | Pronto |
| `backend/teste_ws.html`, servido em `GET /teste` | Pagina antiga de teste: abre o socket, manda os chunks e escreve na tela o que voltar. Nao conhece nenhuma mensagem do protocolo | Pronto, so para teste de transporte |

A constante `URL_WEBSOCKET` do `frontend/app.js` monta o endereco com `location.host`, entao a tela herda sozinha a porta de quem serviu a pagina: nao ha endereco fixo para corrigir quando a porta mudar.

Para exercitar o que existe:

```
npm run dev
```

Sobe o Postgres no Docker e o uvicorn na porta 3000. A tela fica na raiz, `http://localhost:3000`; o socket, em `/ws/falar`. Com a chamada ligada, o terminal do uvicorn imprime uma linha `[websocket] recebi e guardei um chunk de N bytes` a cada 250 ms.

## Telas

Nenhuma propria. Quem consome este protocolo e a tela de chamada (ATD-01), na raiz do servidor. A pagina `backend/teste_ws.html`, em `/teste`, existe desde antes do protocolo e so exercita o transporte binario.

## Escopo

### Regra basica dos frames (pronto)

Duas regras, e so duas:

1. **Frame binario e audio.** Da tela para o servidor sao os pedacos do microfone; do servidor para a tela sao os pedacos do audio de resposta.
2. **Frame de texto e JSON de controle, sempre com a chave `tipo`.** Qualquer outro texto nao e protocolo.

Texto que nao e JSON valido, ou JSON sem a chave `tipo`, cai no log da tela e para por ali (`tratarMensagem` escreve `"backend: " + evento.data` e retorna). E por isso que o eco atual do servidor, o `send_text("chunk guardado no backend!")` que sai a cada chunk gravado, convive com o protocolo sem quebrar nada. O `escreverLog` ainda agrupa a repeticao numa linha so, com um contador no fim, senao seriam quatro linhas de log por segundo.

Do lado do servidor a mesma tolerancia existe em dois pontos: texto que nao e JSON e capturado no `json.JSONDecodeError` e vira `print` (`[websocket] texto que nao eh json, ignorei: ...`), e JSON com um `tipo` desconhecido cai no `else` final (`[websocket] controle desconhecido, ignorei: ...`). Nos dois casos o laco continua; nenhum frame estranho derruba a conexao.

A versao do protocolo e 1, declarada pelos dois lados. Dinheiro trafega como **string com duas casas**, feita com `str(Decimal)` e nunca com `float()`: `float` transforma 79.80 em 79.8 e 91.00 em 91, que nao e formato de dinheiro. A tela aceita numero por seguranca (`formatarDinheiro` converte e registra no log quando o valor vem fora do formato), mas quem manda string nao perde centavo.

### Mensagens da tela para o servidor (pronto na tela, quatro de cinco tratadas no servidor)

| Tipo | Quando e enviada | Campos | O que o servidor faz hoje |
|---|---|---|---|
| (frame binario) | A cada `TAMANHO_CHUNK_MS` = 250 ms, **so enquanto o estado da tela e "ouvindo"** | Os bytes do `MediaRecorder` | Escreve no arquivo aberto e responde `send_text("chunk guardado no backend!")` |
| `iniciar_chamada` | Uma vez, no instante em que o servidor se apresenta com o `pronto` | `versao_protocolo` (1), `formato_audio` (ex.: `audio/webm;codecs=opus`), `chunk_ms` (250) | Le `controle.get("formato_audio")` e guarda em `formato_do_audio`. Ninguem usa a variavel ainda: e a transcricao que vai precisar dela |
| `fim_da_fala` | Quando o detector de silencio fecha o turno, ou aos 15 s de fala continua. O microfone ja foi pausado antes do envio | `turno`, `duracao_ms` | So `print`. E o ponto exato onde entra a transcricao (`--- MOCK DA FASE 3 ---`) |
| `resposta_tocada` | Quando o audio de resposta termina de tocar e o microfone ja foi reaberto | `turno` | So `print` |
| `timeout` | Quando nada chegou em `ESPERA_RESPOSTA_MS` = 15 s e a tela reabriu o microfone sozinha | `turno` | **Nao tratado**: cai no `else` de controle desconhecido |
| `encerrar_chamada` | Quando o cliente clica em Desligar. Hoje o unico motivo emitido e `cliente_desligou` | `motivo` | `print`, `await websocket.close()` e sai do laco |

O campo `turno` que a tela manda e conferencia: o servidor pode ecoar ou ignorar. A contagem comeca em zero a cada `ligar()` e sobe em `fimDaFala`.

Nenhuma dessas cinco mensagens de texto sai do navegador hoje. `enviarTexto` comeca com `if (!protocoloNovo) return;`, e `protocoloNovo` so vira `true` quando o servidor manda o `pronto` — o que nao acontece. O unico trafego real de subida e o binario. Consequencia pratica: o `encerrar_chamada` nunca chega, e o servidor descobre o fim da chamada pelo `WebSocketDisconnect` quando a tela fecha o socket.

### Mensagens do servidor para a tela (nao implementado)

Nenhuma delas e enviada hoje. A tela trata todas as nove.

| Tipo | Campos | Efeito na interface |
|---|---|---|
| `pronto` | `versao_protocolo` | Tira a tela do modo mudo, escreve no log "servidor pronto, protocolo versão N", esconde o aviso de prototipo da comanda e dispara o `iniciar_chamada` de volta |
| `estado` | `etapa` (`ouvindo`, `transcrevendo`, `pensando`, `respondendo`, `ocioso`), `turno` | Acende a etapa correspondente na tira do topo, troca o rotulo do orbe e **rearma o relogio de 15 s**. `ouvindo` reabre o microfone e volta ao estado "Pode falar"; `ocioso` apaga a tira e desarma o relogio |
| `transcricao` | `turno`, `quem` (`cliente` ou `atendente`), `texto`, `parcial` | Escreve na conversa. `parcial: true` mantem um bloco por lado, em italico, reescrito a cada mensagem; `parcial: false` fecha o bloco. Serve para a transcricao incremental e para o streaming de token do Ollama |
| `audio_resposta` | `turno`, `formato` (ex.: `audio/wav`) | So o aviso: liga a espera dos frames binarios, limpa o buffer, rearma o relogio e marca a etapa 4. **Binario que chega sem esse aviso e ignorado** |
| (frames binarios) | Os bytes do audio sintetizado | Sao acumulados em memoria; nada toca ainda |
| `fim_audio` | Nenhum | Junta os frames num `Blob` com o formato anunciado e toca. **Mande sempre**, mesmo com um frame unico |
| `pedido` | `turno`, `cliente` (`nome`, `telefone`), `itens[]` (`produto`, `quantidade`, `preco_unitario`, `observacao`), `total`, `forma_pagamento`, `endereco_entrega` | Redesenha a comanda inteira: item novo fica em destaque por 4 s, o subtotal e calculado na tela (`preco_unitario` x `quantidade`) e o cabecalho mostra cliente, pagamento, entrega e total |
| `pedido_salvo` | `pedido_id`, `total` | Guarda o numero do pedido e esconde o aviso da comanda. **Tem que chegar antes do `chamada_encerrada`**, senao o resumo abre com o titulo "Pedido não salvo" |
| `erro` | `onde` (`captura`, `audio`, `transcricao`, `llm`, `ollama`, `sintese`, `piper`), `mensagem`, `fatal` | Abre a tarja de aviso e pinta como "falhou" a etapa correspondente ao `onde` (captura e audio -> 1, transcricao -> 2, llm e ollama -> 3, sintese e piper -> 4). `fatal: true` derruba a chamada; `fatal: false` e so o aviso |
| `chamada_encerrada` | `motivo` | Encerra a chamada, mantem o socket aberto por `ESPERA_PEDIDO_SALVO_MS` = 1,2 s para caber um `pedido_salvo` atrasado, e so entao abre o resumo |

O `pedido` e **plano**: `cliente`, `itens`, `total`, `forma_pagamento` e `endereco_entrega` ficam no nivel de cima da mensagem, ao lado do `tipo`, e nao dentro de uma chave `pedido`. Foi assim que a tela foi escrita: `aplicarMensagem` guarda a mensagem inteira como se fosse o pedido.

### Aperto de mao: a tela nasce muda (parcial)

A tela comeca cada chamada com `protocoloNovo = false` e nao manda **nenhum** frame de texto enquanto essa variavel for falsa. Isso existe por causa do backend antigo, que usava `receive_bytes()` e morria ao receber texto; a tela evita o problema nao falando ate ser convidada.

O convite e o `pronto`, e so ele. Em `tratarMensagem`, um JSON com `tipo: "pronto"` liga o protocolo, esconde o aviso de prototipo e faz a tela mandar o `iniciar_chamada`; so depois a mensagem e processada pelo `switch`. Qualquer outro frame tipado que chegue antes do `pronto` e aplicado normalmente, mas **nao** tira a tela do modo mudo — vai para o log e o envio de texto continua bloqueado. Ela e a unica mensagem cujo unico proposito e se apresentar, e e por isso que ela e o convite.

**O servidor nao manda o `pronto` hoje, de proposito.** A linha existe pronta em `backend/main.py`, logo depois do `accept()`, comentada:

```python
# --- QUANDO A TRANSCRICAO ESTIVER PRONTA, DESCOMENTE ESTA LINHA ---
# await websocket.send_json({"tipo": "pronto", "versao": 1})
# ------------------------------------------------------------------
```

E a **linha 75** de `backend/main.py`. Se ela fosse descomentada agora, a tela sairia do modo mudo, mandaria `fim_da_fala` a cada pausa e ficaria esperando transcricao, estado e audio que nunca viriam, ate estourar o relogio de 15 s e mostrar "O servidor demorou demais para responder". Com a tela muda, a demonstracao e honesta: conecta, grava, nao recebe resposta e a comanda diz na cara que o servidor ainda nao envia o pedido.

Quando a transcricao existir, descomentar a linha 75 e o unico passo do lado do aperto de mao: a tela liga o protocolo novo sozinha. Ao descomentar, trocar `"versao"` por `"versao_protocolo"` (ver Questoes em aberto).

### Sequencia de um turno completo (nao implementado do lado do servidor)

Hoje existem so os passos 1 e 4; o passo 5 acontece pela metade (o detector de silencio dispara e escreve no log, mas nao pausa a captura nem envia nada, porque o `return` do backend antigo vem antes do `pausarCaptura()`) e os passos 6, 11 e 12 dependem de descomentar a linha 75. Os demais dependem de VOZ-01.

1. O cliente clica em Ligar. A tela pede o microfone, abre o WebSocket com ate `ESPERA_SOCKET_MS` = 5 s de paciencia e entra no estado "ouvindo".
2. O servidor aceita e manda `{"tipo":"pronto","versao_protocolo":1}` (linha 75, hoje comentada).
3. A tela sai do modo mudo e responde `iniciar_chamada` com o formato real do gravador e o tamanho do chunk.
4. Microfone aberto: frames binarios de 250 ms sobem continuamente, e so nesse estado. O medidor de nivel roda em paralelo e desenha as barras.
5. A tela decide que a fala terminou: voz acima de `RMS_FALA` por 300 ms seguida de 1,2 s sem passar de `RMS_FALA`, ou 15 s de fala continua. **Aqui comeca o meia-duplex**: `fimDaFala` chama `pausarCaptura()` antes de qualquer envio, e o gravador para de emitir (`pause()`) com as faixas do microfone desabilitadas (`track.enabled = false`). Nenhum byte mais sobe.
6. A tela incrementa o turno, manda `fim_da_fala` com `turno` e `duracao_ms`, acende a etapa 2 e arma o relogio de 15 s.
7. O servidor manda `estado: transcrevendo`, transcreve o turno e manda `transcricao` com `quem: "cliente"` (uma ou mais parciais, depois a definitiva).
8. O servidor manda `estado: pensando`, consulta cardapio e historico, monta a resposta e, se o pedido mudou, manda `pedido` com a comanda atualizada e a `transcricao` do atendente.
9. O servidor manda `estado: respondendo`, depois `audio_resposta` com o formato, depois os frames binarios da sintese, depois `fim_audio`. Cada `estado` rearma o relogio de 15 s, entao o modelo local pode demorar o quanto precisar sem a tela desistir.
10. A tela junta os frames e toca. O estado vira "falando" e **o microfone continua fechado** — e o outro lado do meia-duplex. Um `estado: ouvindo` que chegue nesse instante e ignorado de proposito, com registro no log.
11. O audio termina: a tela chama `retomarCaptura()`, manda `resposta_tocada` com o turno, escreve o tempo do turno no rodape e volta para "ouvindo". **Fim do meia-duplex**; o proximo turno recomeca no passo 4.
12. Se nada chegar em 15 s, a tela mostra o aviso "O servidor demorou demais para responder. Pode falar de novo.", manda `timeout` e reabre o microfone por conta propria. A chamada continua.
13. A chamada acaba de um dos dois lados: ou o cliente clica em Desligar e a tela manda `encerrar_chamada` com `motivo: "cliente_desligou"` antes de fechar o socket, ou o servidor manda `chamada_encerrada` e a tela espera 1,2 s por um `pedido_salvo` atrasado antes de abrir o resumo.

O meia-duplex nao e escolha de conforto: e o que impede o proprio audio do atendente de voltar pelo microfone e ser transcrito como fala do cliente. O cancelamento de eco do navegador esta ligado (`echoCancellation: true`), mas o corte da captura e a garantia real.

## Dados

Este item nao le nem grava nada no banco. O que importa aqui e que a carga que trafega case com o que o banco aceita, para a orquestracao nao ter que traduzir nomes no meio do caminho.

O `pedido` do protocolo contra o que `salvar_pedido(db, cliente_id, itens, endereco_entrega=None, forma_pagamento=None)` recebe (PED-01):

| Campo no protocolo | Vai para | Observacao |
|---|---|---|
| `itens[].produto` | `itens[i]["produto"]` | Nome como o cliente falou; `salvar_pedido` passa por `buscar_produtos` e recusa produto inexistente ou ambiguo |
| `itens[].quantidade` | `itens[i]["quantidade"]` | Inteiro. Quantidade quebrada e recusada na gravacao, nao arredondada |
| `itens[].observacao` | `itens[i]["observacao"]` | Copiada para `item_pedido.observacao` |
| `itens[].preco_unitario` | Nada | So serve para a tela calcular o subtotal. Quem grava e `salvar_pedido`, que copia o preco do cardapio com `Decimal(str(produto.preco))`. O valor que trafega nao tem autoridade nenhuma |
| `total` | Nada | Idem: `salvar_pedido` soma em `Decimal` e arredonda com `quantize`. O total do protocolo serve para a comanda e para o resumo |
| `forma_pagamento` | `forma_pagamento` | Um dos quatro valores canonicos (`pix`, `dinheiro`, `cartao_credito`, `cartao_debito`) ou `null`. A tela mostra "a combinar" para `null` e registra no log qualquer outro valor |
| `endereco_entrega` | `endereco_entrega` | Texto ou `null`; `salvar_pedido` cai no endereco cadastrado do cliente quando vem vazio |
| `cliente.nome`, `cliente.telefone` | Nada | So exibicao na comanda e no resumo |
| — | `cliente_id` | **Nao trafega no protocolo** e e obrigatorio na gravacao. Ver Questoes em aberto |
| `pedido_salvo.pedido_id` | Vem do `id` do pedido depois do commit | E o que faz o resumo dizer "Pedido registrado" em vez de "Pedido não salvo" |

CPF nunca trafega em nenhum frame, em nenhuma direcao (CLI-01, RNF06). O que a tela mostra do cliente e nome e telefone.

O audio gravado pelo servidor vai para `audio_cliente_streaming.webm`, caminho fixo relativo ao diretorio de trabalho do uvicorn (`backend/`), aberto em modo `"wb"` no inicio da conexao.

## Acoes e regras

- Binario e audio, texto e JSON com `tipo`. Nao existe terceira categoria.
- A tela so manda frame de texto depois que o servidor mandar um JSON com `tipo`. Antes disso, `enviarTexto` retorna sem fazer nada.
- Binario so sobe com o microfone aberto: o `ondataavailable` verifica `estadoAtual !== "ouvindo"` e descarta o pedaco. A resposta do atendente nunca volta para o servidor.
- Meia-duplex: entre o `fim_da_fala` e o `resposta_tocada` o microfone fica fechado. Um `estado: ouvindo` durante a reproducao e ignorado.
- Mensagem desconhecida vai para o log e nao derruba a tela. Nos dois sentidos: `tipo` fora do `switch` cai no `default` e vira uma linha de log; `etapa` fora das cinco, `quem` fora de `cliente`/`atendente` e `forma_pagamento` fora das quatro tambem so registram e seguem. No servidor, texto que nao e JSON e `tipo` desconhecido viram `print` e o laco continua.
- O pedido que trafega usa os mesmos nomes de campo do banco e e plano. Os nomes dos itens tem que ser os que `salvar_pedido` espera, senao a orquestracao traduz duas vezes o mesmo dado.
- Dinheiro sempre como string de duas casas, feita com `str(Decimal)`.
- `audio_resposta` antes dos bytes, `fim_audio` depois. Binario orfao e descartado.
- `pedido_salvo` antes de `chamada_encerrada`, ou o resumo abre errado.
- O `turno` e conferencia, nao chave: quem manda o proximo passo e a sequencia das mensagens.
- `encerrar_chamada` fecha o socket na mao (`await websocket.close()`). So sair da funcao nao manda o frame de close, e a tela ficaria esperando um fim que nunca chega.
- Versao 1 declarada dos dois lados, e nenhum dos dois valida a do outro hoje.

## Casos de borda

As duas armadilhas ja conhecidas vem primeiro.

| Situacao | Comportamento |
|---|---|
| **Frame de texto lido com `receive_bytes()`** | Era o bug que derrubava a conexao: a mensagem do ASGI chega com a chave `text` e o `receive_bytes` procura `bytes`, levantando `KeyError`. Como `KeyError` nao e `WebSocketDisconnect`, ele escapava do `except` e matava o laco inteiro com o cliente ainda ligado. Resolvido trocando por `mensagem = await websocket.receive()`, que devolve o dicionario cru: o codigo checa `mensagem["type"] == "websocket.disconnect"` e levanta o `WebSocketDisconnect` na mao, depois olha `mensagem.get("bytes")` e `mensagem.get("text")` e decide. Quem mexer nesse laco nao pode voltar para `receive_bytes()`. |
| **O audio de cada turno precisa ser um arquivo valido** | Hoje o servidor abre **um arquivo so** por conexao, em `"wb"`, e concatena todos os chunks da chamada inteira. Isso guarda a gravacao, mas nao serve como esta para a transcricao por turno: o cabecalho do WebM vem so no primeiro pedaco que o `MediaRecorder` emite, entao um pedaco do meio, isolado, nao abre em nenhum decodificador. Pior, a tela **pausa e retoma** o mesmo gravador entre os turnos (`pause()` e `resume()`) em vez de reinicia-lo: o arquivo e um fluxo continuo, sem marca de onde um turno acabou e o outro comecou. Quem implementar a transcricao precisa escolher um dos dois caminhos, e nao ha decisao tomada: decodificar o fluxo continuo e fatiar em PCM no servidor, ou fazer a tela parar e recriar o gravador a cada turno, o que produz um arquivo fechado e valido por turno ao custo de um pequeno buraco de audio na virada. |
| Binario chega sem `audio_resposta` antes | Descartado, com a linha "chegou binário sem aviso de audio_resposta, ignorado" no log |
| `fim_audio` sem nenhum frame binario antes | Nada toca, o log registra e a tela volta sozinha para "ouvindo" |
| O servidor esquece o `fim_audio` | Rede de seguranca: `ESPERA_FIM_AUDIO_MS` = 800 ms depois do ultimo frame binario a tela fecha o Blob e toca o que chegou |
| O servidor passa 15 s sem mandar nada | A tela avisa, manda `timeout` e reabre o microfone. Cada mensagem de `estado` rearma esse relogio, entao a forma de pedir mais tempo e mandar estado |
| O servidor recebe `timeout` | Cai no `else` de controle desconhecido e so imprime. O turno fica dessincronizado: o servidor pode responder um turno que a tela ja abandonou |
| `iniciar_chamada` nunca chega | O servidor nao manda o `pronto`, entao a tela fica muda e `formato_do_audio` permanece `None`. E o estado normal enquanto o pipeline nao existir |
| `pronto` com `versao` em vez de `versao_protocolo` | A tela liga o protocolo normalmente e escreve "servidor pronto, protocolo versão undefined" no log. Defeito cosmetico, mas visivel numa demonstracao |
| `estado: ouvindo` com a resposta tocando | Ignorado, com registro no log: o meia-duplex tem precedencia sobre o pedido do servidor |
| `etapa` ou `quem` desconhecido | Log e nada mais; a conversa e a tira do topo ficam como estavam |
| `forma_pagamento` fora das quatro | A comanda mostra "a combinar" e o log registra o valor recusado |
| `pedido_salvo` depois do `chamada_encerrada` | Cabe, desde que chegue dentro de 1,2 s: o socket fica aberto nessa janela so por isso. Depois disso o resumo abre com "Pedido não salvo" mesmo que o pedido tenha ido ao banco |
| O socket cai no meio da chamada | A tela distingue queda de fechamento proprio pela flag `fechamosOSocket` e mostra "A conexão com o servidor caiu no meio da chamada." |
| O backend nao esta rodando | O socket fecha em milissegundos sem nunca ter aberto; a tela nao culpa a queda e diz "Não consegui falar com o servidor. Confira se o backend está rodando (npm run dev)." |
| O cliente fala por cima da resposta do atendente | Nao resolvido. O protocolo espera o `resposta_tocada` antes do proximo turno; interrupcao esta fora de escopo neste semestre |
| Duas abas abrem a chamada ao mesmo tempo | As duas conexoes abrem o mesmo `audio_cliente_streaming.webm` em `"wb"`: a segunda trunca o arquivo da primeira. O caminho e fixo e nao ha identificador de sessao |
| A tela fecha sem mandar `encerrar_chamada` | E o que acontece hoje em toda chamada, porque a tela esta muda. O servidor cai no `WebSocketDisconnect`, imprime e fecha o arquivo normalmente |

Nada disso foi medido: nao existe teste automatizado do protocolo no repositorio, e os limiares citados (250 ms de chunk, 15 s de espera, 800 ms de fim de audio, 1,2 s de janela do `pedido_salvo`) foram escolhidos na mao. Fechar esses numeros com medicao e MED-01.

## Fora de escopo

- Transcricao, modelo de linguagem, sintese, deteccao de atividade de voz e a orquestracao que produz as mensagens do servidor: VOZ-01, nao implementado.
- O desenho da tela, a tira de etapas, a comanda e o resumo: ATD-01.
- Validacao de item contra o cardapio, montagem e gravacao do pedido: PED-01 e `backend/repositorio.py`.
- Identificacao do cliente e tratamento do CPF: CLI-01.
- Medicao de latencia por etapa e do tempo entre o `fim_da_fala` e o primeiro byte de audio de resposta: MED-01.
- Autenticacao, sessao com identificador, mais de uma chamada simultanea, reconexao com retomada de estado, compressao de frame e versao 2 do protocolo.
- Interrupcao do atendente pelo cliente e full-duplex.
- Telefonia real: o transporte deste semestre e WebSocket de navegador, nao SIP nem WebRTC.

## Questoes em aberto

- O nome do campo do formato chegou a nao casar entre os dois lados (a tela mandava `formato_audio` e o servidor lia `formato`). Corrigido no servidor, que passou a ler `formato_audio`: o cabecalho de `frontend/app.js` e o contrato publicado e a tela ja estava escrita nesse nome.
- O `pronto` comentado na linha 75 manda `{"tipo": "pronto", "versao": 1}` e a tela le `versao_protocolo`. Recomendacao: ao descomentar, escrever `{"tipo": "pronto", "versao_protocolo": 1}`, alinhando com o campo que a tela ja usa e com o `iniciar_chamada` que ela responde.
- O servidor nao trata `timeout`. Ele e o unico aviso de que a tela desistiu do turno e reabriu o microfone, e e exatamente quando o servidor precisa descartar a resposta em andamento. Recomendacao: tratar no mesmo `switch`, cancelando o turno em curso e voltando para `estado: ouvindo`, antes de a primeira resposta real existir — depois fica caro.
- `cliente_id` nao trafega no protocolo e `salvar_pedido` exige. Recomendacao: o servidor guardar o `cliente_id` na memoria da conexao assim que a identificacao acontecer (CLI-01) e nunca manda-lo para a tela; a tela so precisa de nome e telefone para a comanda. Mandar o id para o navegador nao acrescenta nada e abre uma porta que ninguem quer.
- O formato do audio de resposta nao esta fechado. A tela usa o campo `formato` do `audio_resposta` como tipo do Blob e cai em `audio/wav` quando ele nao vem; VOZ-01 registra que a voz do Piper ainda nao foi escolhida. Recomendacao: fechar em `audio/wav` na primeira versao, que e o que o Piper produz nativamente e o que todo navegador toca, e so pensar em formato comprimido se a transferencia aparecer como custo na medicao de MED-01.
- Ninguem valida a versao do protocolo. Os dois lados declaram 1 e os dois ignoram o numero do outro. Recomendacao: quando houver uma versao 2, o servidor recusar versao diferente com `erro` de `fatal: true` em vez de tentar adivinhar; enquanto so existe a versao 1, o custo de nao validar e zero.
- O eco `"chunk guardado no backend!"` sai a cada 250 ms so para confirmar que o chunk chegou. Recomendacao: remover junto com o descomentar da linha 75; com o protocolo ligado, quem informa progresso e a mensagem `estado`, e o eco vira quatro frames por segundo de ruido.
- Um arquivo de audio por conexao, em caminho fixo, sobrescrito a cada chamada. Recomendacao: quando a transcricao entrar, trocar por um caminho com identificador de conexao e de turno dentro de uma pasta ignorada pelo git, para duas chamadas nao disputarem o mesmo arquivo e para sobrar material de teste para o WER de MED-01.
