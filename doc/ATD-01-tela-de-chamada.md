# ATD-01 Tela de chamada

Status: Parcial. A tela esta escrita e redesenhada por inteiro — sete estados de chamada, tira das quatro etapas no topo, comanda ao vivo, resumo do fim, tarja de erro e painel tecnico — e a captura do microfone com envio dos pedacos pelo WebSocket funciona; o que nao acontece e o outro lado: o servidor nunca se apresenta (o `send_json` do `pronto` esta comentado em `backend/main.py`) e o pipeline nao existe, entao hoje a tela conecta, grava, manda binario e nao recebe transcricao, audio, pedido nem resumo.

Backlog: doc/backlog.md (ATD-01). Requisitos: RF01, RF11, RNF03; a tira de etapas e a superficie onde RNF01 e RIA07 aparecem para quem esta olhando.

## Objetivo

Ser a unica interface do sistema: o lugar onde o cliente liga, fala, ve o que o atendente entendeu, acompanha o pedido sendo montado e recebe o resumo no fim. A tela nao pensa — ela captura audio, desenha o que o servidor manda e devolve tres comandos (comecei, parei de falar, terminei de ouvir). Tudo o que ela mostra alem disso e estado da propria chamada: conexao, duracao, microfone aberto ou fechado, em que etapa do pipeline o turno esta e o que deu errado.

O segundo objetivo, menos obvio, e nao mentir. Enquanto o pipeline nao existir, a tela nao pode simular resposta, nem inventar pedido, nem acender etapa que ninguem executou. Toda animacao da tira de etapas vem de uma mensagem do servidor; sem mensagem, a tira fica parada em "aguardando".

## Usuarios e papeis

| Papel | O que faz na tela |
| :-- | :-- |
| Cliente da pizzaria | Unico usuario real. Clica em "Ligar", fala, ouve, confere a comanda e desliga. Nao ha login, cadastro na tela, formulario nem campo de digitacao: a chamada inteira e operada por um botao. |
| Time e banca | Abrem o `<details>` "Detalhes tecnicos" no rodape para ver o log das mensagens e ouvir a ultima gravacao. E a unica parte da tela que nao e para o cliente. |

Nao existe papel de atendente humano, de gerente nem de cozinha: nao ha tela administrativa, lista de pedidos nem area logada em lugar nenhum do projeto.

## Pontos de entrada

| Caminho | O que e |
| :-- | :-- |
| `frontend/index.html` | Estrutura: cinco faixas (barra de cima, tira de etapas, tarja de erro, corpo, rodape tecnico) mais o resumo modal e o `<audio id="audio-resposta">` |
| `frontend/style.css` | Tema claro, tokens de cor e espaco, os estados desenhados por `body[data-estado]` e as quebras de layout |
| `frontend/app.js` | Todo o comportamento: protocolo, captura, medidor de nivel, comanda, resumo, erros e log |
| `http://localhost:3000` | Onde a tela abre. Quem serve e o `app.mount("/", StaticFiles(directory=PASTA_FRONTEND, html=True))` no fim de `backend/main.py`. **Nao existe `/app`** |
| `ws://<host>/ws/falar` | Conexao unica com o servidor. A URL e montada em `app.js` com `location.host`, entao herda a porta de quem serviu a pagina |

```bash
npm run dev
```

Sobe o Postgres no Docker e o uvicorn na porta 3000. As outras rotas de `backend/main.py` (`/health`, `/teste`, `/api/v1/falar`) existem, mas **a tela nao usa nenhuma delas**: `app.js` nao tem uma unica chamada `fetch`. A rota `/teste` serve o `backend/teste_ws.html`, que e outra pagina, de teste manual do WebSocket, e nao esta coberta por este item.

A tela nao usa `localStorage`, `sessionStorage`, cookie nem parametro de URL: recarregar a pagina zera tudo.

## Telas

Uma so, sem rota interna, sem navegacao e sem scroll de pagina: o `body` e `height: 100vh` com `overflow: hidden` e organiza cinco faixas empilhadas em coluna. O alvo declarado no comentario de abertura do CSS e desktop 1280x800.

### As cinco faixas

| Faixa | Altura | O que tem |
| :-- | :-- | :-- |
| 1. `#barra-topo` | 64px | A marca (uma fatia de pizza feita com `conic-gradient`), o titulo "Pizzaria — atendimento por voz", o chip de conexao (bolinha + palavra) e o bloco CHAMADA com o cronometro `00:00` |
| 2. `#tira-etapas` | 84px | As quatro etapas do pipeline e, na ponta direita, "ultimo turno: — · meta: 5 s" |
| 3. `#tarja-erro` | so aparece quando ha erro | Faixa de largura inteira, fundo rosado, barra vermelha de 4px na esquerda, um X desenhado, a mensagem e um botao |
| 4. `#corpo` | ocupa o resto | Grade de duas colunas: `1fr` para a chamada, `420px` para a comanda |
| 5. `#rodape-tecnico` | 48px | O `<details>` "Detalhes tecnicos"; aberto, sobe um painel de 220px por cima do corpo |

Na coluna da chamada, de cima para baixo: o **cartao de estado** (orbe de 64px com anel e icone, rotulo, sublinha e, na direita, o chip do microfone com as sete barrinhas de nivel), a **caixa de conversa** (rolagem propria, `aria-live="polite"`) e o **botao principal** de 72px ocupando a largura inteira. A coluna da direita e a **comanda**, em papel mais quente (`--comanda`), com cabecalho ("COMANDA / Seu pedido / Cliente: ..."), a lista de itens com rolagem, um espaco reservado para aviso e o rodape com pagamento, entrega, uma regua tracejada e o TOTAL em 32px.

O tema e claro, e a cor de destaque (`--destaque`, `#E4572E`) so e usada como forma: trilho da etapa ativa, anel do orbe em "ouvindo", barrinhas do microfone, chip da quantidade e a marca. Hierarquia e feita por espaco e tipografia, nao por caixa colorida.

### Os estados da chamada

O estado vive em `body[data-estado]` e e o CSS que decide, a partir dele, qual icone aparece no orbe, como o anel se comporta, o que o chip do microfone diz e se as barrinhas estao acesas. Os textos ficam todos juntos no objeto `ESTADOS` de `app.js`:

| Estado | Rotulo e sublinha | Orbe | Microfone | Botao |
| :-- | :-- | :-- | :-- | :-- |
| `ocioso` | "Chamada não iniciada" / "clique em Ligar e fale normalmente" | Microfone riscado, anel cinza parado | Fechado, chip escondido | "Ligar" (triangulo, laranja) |
| `conectando` | "Chamando…" / "abrindo o microfone e a conexão" | Tres pontinhos pulando, anel tracejado girando | Abrindo | "Conectando…", desabilitado |
| `ouvindo` | "Pode falar" / "seu microfone está ligado" | Microfone sem risco, capsula laranja, anel laranja com halo | **Aberto**: chip "MICROFONE ABERTO" e as barrinhas mexendo | "Desligar" (quadrado, tinta escura) |
| `processando` | "Anotando seu pedido…" / "microfone pausado" | Pontinhos, anel com um quarto laranja girando | **Pausado**: chip "MICROFONE PAUSADO", barrinhas no minimo com opacidade .4 | "Desligar" |
| `falando` | "Atendente falando" / "seu microfone fica desligado até ele terminar" | Alto-falante com ondas concentricas se expandindo | **Pausado**, mesmo chip | "Desligar" |
| `encerrada` | "Chamada encerrada" / "duração mm:ss" | Microfone riscado de novo | Solto de vez | "Ligar de novo" |
| `erro` | "Não deu certo" / a propria mensagem do erro | X vermelho, anel vermelho | Solto | "Tentar de novo" |

O botao so fica desabilitado em `conectando`. A sublinha do estado `erro` repete a mensagem por escrito, alem da tarja: quem nao olhar para o topo da tela ainda le o que houve ao lado do orbe.

### A tira de etapas

Fica no **topo**, logo abaixo da barra de titulo, e nao desce nem em tela estreita. Sao quatro colunas iguais — **1 ouvindo, 2 transcrevendo, 3 pensando, 4 respondendo** — e cada uma tem tres partes: um trilho de 4px, um disco numerado de 24px com o nome ao lado e, embaixo, o tempo. Os quatro trilhos lado a lado formam uma barra de progresso atravessando a tela.

| Estado da etapa | Trilho | Disco | Tempo |
| :-- | :-- | :-- | :-- |
| Parada | Cinza | Contorno cinza com o algarismo | "aguardando" |
| Ativa | Laranja, com uma varredura clara passando por cima | Laranja com anel externo claro | "agora", com reticencias piscando postas pelo CSS |
| Concluida | Verde | Verde, e o algarismo **vira um visto** desenhado no CSS | O tempo que ela levou, "1,4 s" |
| Falhou | Vermelho | Vermelho, e o algarismo **vira um X** | "falhou" |

Quem acende cada etapa e a mensagem `estado` do servidor, traduzida por `aplicarEtapa`; quem marca falha e a mensagem `erro`, pelo campo `onde`, com o mapa `captura`/`audio` na 1, `transcricao` na 2, `llm`/`ollama` na 3 e `sintese`/`piper` na 4. Ao trocar de etapa, `marcarEtapa` fecha a anterior guardando quanto tempo ela levou, que e o numero que aparece no lugar de "agora". Fim de chamada e erro fatal fecham com `marcarEtapa(0, { abortada: true })`, que escreve "interrompida" em vez de marcar como concluida: etapa que morreu no meio nao pode aparecer verde e com tempo carimbado, porque esse numero seria lido como leitura de latencia.

E aqui que RNF01 e RIA07 ficam visiveis: o tempo por etapa na tira e o tempo do turno inteiro na ponta direita ("ultimo turno: 3,2 s"), cronometrado em `voltarAOuvir` desde o `fim_da_fala`. **Ressalva que precisa estar dita:** esses numeros sao medidos no navegador, do lado do cliente, e hoje nunca chegam a ser produzidos, porque nenhuma mensagem de estado chega. Eles nao substituem a medicao por etapa no servidor, que e de MED-01 e nao existe. O texto "meta: 5 s" esta escrito fixo no `index.html` e **nao corresponde a nenhuma meta definida**: o RNF01 diz que a meta sai depois de teste no hardware alvo, e nada foi medido (ver Questoes em aberto).

### Conversa, comanda e resumo

A conversa mostra um bloco por fala, com o rotulo "VOCÊ" ou "ATENDENTE". O atendente se distingue por **forma**, nao por cor: uma linha vertical de 2px a esquerda e recuo. Fala parcial (`parcial: true`) sai em italico, em tinta mais fraca e com um cursor piscando no fim; quando o `parcial: false` chega, o mesmo bloco e fechado no lugar, sem duplicar. Vale para os dois lados, entao o modelo respondendo token a token tambem pode escrever ao vivo.

O resumo do fim (RF11) e um modal com veu escuro que reusa exatamente a mesma funcao de desenho da comanda. O titulo e "Pedido registrado" quando chegou `pedido_salvo` e **"Pedido não salvo"** quando nao chegou — sem meio-termo e sem enfeite.

### Telas menores

Nao existe uma segunda tela para celular: existem quatro ajustes do mesmo desenho. Em `max-height: 820px` o orbe e o botao encolhem; em `max-width: 1180px` a comanda passa de 420px para 380px; em `max-width: 980px` as colunas viram uma so, a comanda vai **para cima** da chamada (`order: 1`) e a tira de etapas vira 2x2 sem sair do topo; em `max-width: 760px` a barra de titulo quebra em duas linhas e o painel tecnico vira coluna unica. Isso e o layout se defendendo, nao entrega mobile: ver Questoes em aberto.

## Escopo

### Captura, envio e o protocolo (pronto)

`iniciarCaptura` pede o microfone com `echoCancellation`, `noiseSuppression` e `autoGainControl` ligados, cria o `MediaRecorder` e chama `gravador.start(250)`, entregando um pedaco a cada 250 ms. Cada pedaco vai para o array `pedacos` (que vira o arquivo do player, no painel tecnico) e, **so quando o estado e `ouvindo`**, e enviado como frame binario pelo WebSocket.

A tela nasce muda: `enviarTexto` nao envia nada enquanto `protocoloNovo` for falso, e ele so vira verdadeiro quando chega do servidor o frame `{"tipo":"pronto"}` — outro frame tipado que chegue antes dele e aplicado, mas nao libera o envio de texto. Isso existe porque o servidor de hoje responde `"chunk guardado no backend!"` a cada chunk, que nao e JSON — esse texto cai no log e nao quebra nada. O protocolo completo, com as nove mensagens que entram e as cinco que saem, esta documentado no cabecalho de `frontend/app.js` e e assunto de PRO-01.

### Meia-duplex: por que o microfone fecha (pronto)

O cliente vai usar isto num PC, com a caixa de som ligada. Se o microfone continuasse aberto enquanto o Piper fala, a voz sintetizada sairia pela caixa, voltaria pelo microfone, seria enviada ao servidor e **transcrita como se fosse o cliente**. O atendente responderia a propria fala, que voltaria de novo: um loop que nao para sozinho e que, de quebra, enche o turno de texto falso. O cancelamento de eco do navegador ajuda, mas foi feito para chamada de video com fone, nao para caixa de som aberta com o retorno sendo transcrito — ele reduz o eco, nao garante que ele nao vira texto.

A solucao e meia-duplex: **so um dos dois fala por vez**, e o codigo garante isso em quatro lugares independentes.

1. `fimDaFala` chama `pausarCaptura()` **antes** de mandar o `fim_da_fala`, entao o microfone fecha no instante em que o turno do cliente acaba.
2. `pausarCaptura` faz as duas coisas: `gravador.pause()` (para de emitir pedacos) e `track.enabled = false` (garante que nada entra). Cinto e suspensorio, de proposito.
3. `gravador.ondataavailable` recusa enviar qualquer pedaco fora do estado `ouvindo`. Mesmo que o gravador escape e continue emitindo, o binario nao sai da maquina.
4. `tocarResposta` chama `pausarCaptura()` outra vez antes do `play()`, e `aplicarEtapa("ouvindo")` **ignora** o pedido do servidor para reabrir o microfone enquanto o estado for `falando`.

O microfone so reabre em `voltarAOuvir`, que tem quatro gatilhos, e cada um passa um motivo que decide o frame enviado: o audio terminou (`"tocou"`, manda `resposta_tocada`), os 15 s de espera estouraram (`"timeout"`, manda `timeout`), o audio falhou (`"falha_audio"`, `onerror` ou `play()` rejeitado) ou o `fim_audio` veio sem nenhum frame binario (`"audio_vazio"`). Os dois ultimos **nao mandam frame nenhum**, so linha no log: nao existe mensagem no protocolo para "chegou audio e o cliente nao ouviu", e chamar isso de `resposta_tocada` faria o servidor contar turno falho como turno bem-sucedido na hora de medir latencia. Cada reproducao recebe um numero (`idFala`); trocar o `src` faz a `play()` anterior rejeitar com `AbortError`, e sem esse numero o `catch` da fala velha reabriria o microfone no meio da fala nova.

O estado do microfone nunca fica implicito: o chip escreve "MICROFONE ABERTO" ou "MICROFONE PAUSADO" com todas as letras, o icone do orbe fica riscado quando esta fechado e as sete barrinhas congelam no minimo com opacidade reduzida — prova visual de que nao ha captura.

Consequencia assumida: o cliente **nao pode interromper** o atendente. Isso bate com o que VOZ-01 ja registra como fora de escopo ("cliente fala por cima da resposta: nao resolvido").

### Fim de fala pelo nivel do microfone (pronto, e nao e o VAD do servidor)

`prepararMedidor` liga um `AnalyserNode` no fluxo do microfone e `medirNivel` roda a cada quadro calculando o RMS da janela. As barrinhas sao desenhadas com esse valor e, enquanto o estado e `ouvindo`, `vigiarSilencio` decide o fim do turno com tres constantes declaradas no topo de `app.js`: acima de `RMS_FALA` (0,05) e fala, 300 ms disso confirmam que o cliente falou mesmo, **tudo abaixo de `RMS_FALA` conta como silencio**, e 1,2 s de silencio depois de fala confirmada fecham o turno. Fala continua por 15 s fecha o turno a forca. Havia um segundo limiar (`RMS_SILENCIO`, 0,02) que criava uma zona morta: com ruido de fundo constante entre 0,02 e 0,05 o silencio nunca comecava a contar e a chamada ficava presa em "ouvindo", com o microfone aberto e binario subindo. A histerese ficou so na entrada: para comecar a contar fala e preciso passar de `RMS_FALA`.

Isto e um detector de silencio no navegador, nao a deteccao de atividade de voz do servidor prevista em VOZ-01, que nao existe. Os limiares foram escolhidos na escrita do codigo e **nao foram calibrados com medicao**.

### Negociacao do formato de gravacao (pronto)

O `MediaRecorder` nao grava o mesmo container em todo navegador, e a transcricao precisa saber o que vai abrir. `escolherFormato` percorre `audio/webm;codecs=opus`, `audio/webm`, `audio/ogg;codecs=opus` e `audio/mp4`, devolvendo o primeiro que `MediaRecorder.isTypeSupported` aceitar; se nenhum passar, o gravador e criado sem `mimeType` e o navegador escolhe. Depois disso vale `formatoEmUso`, que le `gravador.mimeType` — **o que o gravador usou de verdade**, nao o que foi pedido — e e esse valor que vai no campo `formato_audio` do `iniciar_chamada` e que rotula o Blob do player.

A chave enviada e `formato_audio`, que e a mesma que o `backend/main.py` le. O nome do campo esta fechado em PRO-01.

### Comanda ao vivo e resumo final (pronto)

`desenharPedido` e uma funcao so, usada nos dois destinos: a comanda da chamada e a caixa do resumo. Cada item vira uma linha com a quantidade num chip arredondado, o nome do produto, a observacao embaixo quando existe, um pontilhado de conta levando o olho ate a direita e o subtotal. O subtotal e calculado na tela (`preco_unitario` vezes `quantidade`), porque o protocolo manda os mesmos campos do banco. Dinheiro e formatado por `formatarDinheiro`, que aceita a string de duas casas combinada no protocolo e tambem numero, por seguranca; valor irreconhecivel vira "—" e uma linha no log, nunca campo em branco. A forma de pagamento so e escrita se for uma das quatro que o banco aceita (`pix`, `dinheiro`, `cartao_credito`, `cartao_debito`), traduzida para "Pix", "Dinheiro", "Cartão de crédito" e "Cartão de débito"; qualquer outra coisa vira "a combinar" mais uma linha no log.

Item que aparece pela primeira vez no turno ganha fundo laranja claro, barra lateral e um selo "NOVO" que **sai sozinho depois de 4 s** — o destaque serve para o cliente notar a mudanca, nao para ficar na tela. A comparacao e feita por `chavesDosItens`, sendo a chave o produto, a quantidade e a observacao juntos.

O resumo abre no `chamada_encerrada` ou quando o proprio cliente desliga, traz "Pedido nº 42 · Duração da chamada: 01:23" e repete itens, pagamento, entrega e total. Quando quem encerra e o servidor, a tela segura o WebSocket por mais 1,2 s antes de fechar, para o `pedido_salvo` atrasado ainda entrar no resumo; se o cliente ja tiver ligado de novo nesse meio tempo, o resumo nao abre.

### Painel de detalhes tecnicos (pronto)

Um `<details>` fechado no rodape, com duas colunas: o player da ultima gravacao ("só para teste") e o log. O log guarda 200 linhas com hora, em fonte monoespacada, e **junta repeticao**: o `"chunk guardado no backend!"` que chega a cada 250 ms vira uma linha unica com o contador `(×N)` em vez de centenas de linhas. Tudo o que a tela faz passa por ali — formato escolhido, conexao aberta e fechada, mensagem desconhecida, valor de dinheiro fora do formato, etapa desconhecida, erro do servidor. E o painel que torna a chamada auditavel sem abrir o console do navegador, e ele existe para o time e para a banca, nao para o cliente.

### Acessibilidade (pronto no que o HTML e o CSS conseguem garantir)

Uma das personas do projeto tem 71 anos, e isso esta escrito no comentario de abertura do CSS como a razao das escolhas abaixo.

- **Texto grande por padrao.** Corpo 17px, fala da conversa 21px, item da comanda 20px, total 32px, rotulo de estado 24px. Nada de 12px ou 13px fora dos rotulos em caixa alta e do log tecnico.
- **Estado nunca sinalizado so por cor.** A bolinha de conexao sempre vem acompanhada da palavra ("desconectado", "conectando", "conectado", "erro de conexão"); a etapa concluida troca o algarismo por um **visto** e a que falhou por um **X**, alem de mudar de cor, e ainda escreve "falhou"; o microfone fechado tem chip escrito, icone riscado e barrinhas congeladas; erro e uma tarja de largura inteira com X, texto e botao, nunca um ponto vermelho sozinho.
- **Alvo de clique grande.** Botao principal de 72px de altura ocupando a largura da coluna (64px em tela baixa); botao da tarja, botoes do resumo e o proprio "Detalhes técnicos" com `min-height: 48px`.
- **Foco visivel em tinta, nao em cor tematica.** `:focus-visible` desenha contorno de 3px em `--tinta` com 2px de folga. A folga positiva poe o anel **fora** da caixa do controle, sobre o fundo da pagina — ele nunca cai sobre o preenchimento do botao laranja, e e por isso que aparece igual em todos os controles. O comentario do CSS registra `--tinta` sobre `--fundo` e sobre `--superficie`; **nao ha medicao de contraste registrada com ferramenta** — isso e trabalho de MED-01. A excecao e o `summary` do rodape tecnico, que preenche os 48px da faixa e ficaria com o arco de baixo fora da viewport: la o anel e desenhado para dentro (`outline-offset: -3px`).
- **Leitor de tela.** `#cartao-estado`, `#conversa` e `#comanda-itens` sao `aria-live="polite"`, a tarja de erro e `role="alert"`, o resumo e `role="dialog"` com `aria-modal` e `aria-labelledby`, e todo desenho decorativo (orbe, icones, barrinhas, regua, pontilhado) esta com `aria-hidden="true"` para nao virar ruido.
- **O resumo prende o foco.** Ao abrir, a tela guarda quem tinha o foco e foca o botao primario ("Ligar de novo"); enquanto ele esta aberto, Tab e Shift+Tab circulam so entre os dois botoes do resumo, e ao fechar o foco volta para onde estava (ou para o botao de chamada). Sem isso o `aria-modal="true"` prometia um isolamento que o teclado nao entregava: o leitor de tela ignorava o resto da pagina e o Tab continuava passeando por ela atras do veu.
- **Teclado.** O Esc fecha o resumo. Ao abrir, o foco vai para o botao "Fechar". Nao ha armadilha de foco dentro do modal nem devolucao do foco ao botao de origem: falta assumida, ver Questoes em aberto.
- **Menos animacao.** `prefers-reduced-motion: reduce` reduz toda animacao e transicao a 0,01ms. O comentario do CSS registra que as barrinhas continuam se mexendo mesmo assim, porque a altura delas e `transform` escrito pelo JS a cada quadro, nao animacao CSS.

### O que a tela deliberadamente nao faz (pronto, e e o ponto)

Nao ha modo de demonstracao, nao ha resposta de mentira, nao ha item de exemplo na comanda e nao ha etapa que acenda por conta propria. `fimDaFala` detecta o fim da fala e, se o servidor nao falar o protocolo novo, escreve `"fim da fala detectado (não enviado: backend antigo)"` no log e **nao muda o estado da tela** — nao finge que esta transcrevendo. Enquanto o servidor nao se apresentar, a comanda mostra o aviso "O servidor ainda não envia o pedido — você está vendo o protótipo".

## Dados

A tela nao tem banco, nao tem armazenamento local e nao persiste nada. Tudo o que ela mostra vem de uma mensagem do WebSocket e morre quando a pagina recarrega.

| Mensagem do servidor | Campos usados | Onde aparece |
| :-- | :-- | :-- |
| `pronto` | `versao_protocolo` | Log; e ela que tira a tela do modo mudo |
| `estado` | `etapa` | Tira de etapas e estado do cartao |
| `transcricao` | `quem`, `texto`, `parcial` | Caixa de conversa |
| `audio_resposta` + frames binarios + `fim_audio` | `formato` | Reproduzido no `<audio id="audio-resposta">` |
| `pedido` | `cliente.nome`, `cliente.telefone`, `itens[].produto`, `.quantidade`, `.preco_unitario`, `.observacao`, `total`, `forma_pagamento`, `endereco_entrega` | Comanda e, depois, resumo |
| `pedido_salvo` | `pedido_id`, `total` | Titulo e numero do pedido no resumo |
| `erro` | `mensagem`, `onde`, `fatal` | Tarja, etapa marcada como falhou, sublinha do estado |
| `chamada_encerrada` | `motivo` | Log, encerramento da chamada e abertura do resumo |

Em memoria, durante a chamada: o ultimo `pedido` recebido, o `pedido_id`, as chaves dos itens ja mostrados, os pedacos do audio do cliente (para o player) e os frames do audio de resposta ate o `fim_audio`.

**CPF nunca aparece na tela.** O protocolo so carrega `nome` e `telefone` do cliente, e o telefone e apenas formatado para leitura. O CPF e falado e tratado no servidor (CLI-01), e no banco so existe como hash (RNF06).

O audio do cliente vira um Blob local exibido no player do painel tecnico; o audio da resposta vira um Blob que e tocado e descartado. Nenhum dos dois e baixado, salvo em disco pelo navegador ou enviado para outro lugar alem do proprio WebSocket.

## Acoes e regras

- **Binario so sai com o microfone aberto.** Fora do estado `ouvindo`, `ondataavailable` descarta o envio. A voz do atendente nunca volta para o servidor.
- **A tela nasce muda.** Nenhum JSON e enviado antes de o servidor mandar um JSON com `tipo`. Texto que nao for JSON com `tipo` vai para o log e nao quebra a tela.
- **O servidor manda a etapa, a tela obedece — com uma excecao:** `ouvindo` e ignorado enquanto a resposta esta tocando.
- **Cada mensagem de estado reinicia o relogio de 15 s.** O Llama pode demorar o que precisar entre uma etapa e outra sem a tela concluir que o servidor morreu.
- **Binario sem aviso e ignorado.** Frame binario que chega sem um `audio_resposta` antes vira uma linha de log e e descartado, para nao tocar lixo.
- **Dinheiro nao some da tela.** Valor fora do formato vira "—" e uma linha no log.
- **Forma de pagamento so e escrita se for uma das quatro do banco.** Qualquer outra vira "a combinar".
- **O resumo diz a verdade sobre o banco.** Sem `pedido_salvo`, o titulo e "Pedido não salvo".
- **Erro fatal derruba a chamada; erro nao fatal e so uma tarja.** O botao da tarja muda junto: "Tentar de novo" religa, "Fechar aviso" so esconde.
- **Desligar solta o microfone de verdade.** `encerrar` para o gravador, para as trilhas (`track.stop()`), fecha o `AudioContext` e para o cronometro, para o indicador de gravacao do navegador apagar.
- **Fechar a aba no meio da chamada tambem limpa.** O `beforeunload` solta as trilhas e fecha o WebSocket marcando que o fechamento foi nosso.

## Casos de borda

| Situacao | O que a tela faz |
| :-- | :-- |
| **Microfone negado** (`NotAllowedError`, `SecurityError`, `PermissionDeniedError`) | Tarja fatal com a instrucao exata: "Clique no cadeado ao lado do endereço e permita o microfone para este site". O cronometro para, o estado vai para `erro`, o orbe mostra o X e a comanda avisa "Este pedido ainda não foi salvo." O WebSocket nem chega a ser aberto |
| **Sem microfone no computador** (`NotFoundError`, `DevicesNotFoundError`) | Mesma tarja, texto proprio: "Nenhum microfone foi encontrado neste computador." |
| **Navegador sem `MediaRecorder`** | Detectado no carregamento da pagina: aviso nao fatal "Este navegador não grava áudio. Use o Chrome ou o Edge." Ao clicar em Ligar, vira erro fatal |
| **Backend desligado** | O WebSocket fecha em milissegundos sem nunca ter aberto; a tela distingue os dois casos com a marca `abriu` e mostra "Não consegui falar com o servidor. Confira se o backend está rodando (npm run dev)." Se travar sem abrir nem fechar, o limite de 5 s desiste |
| **WebSocket cai no meio da chamada** | `onclose` sem fechamento pedido por nos, com a chamada em andamento, gera erro fatal "A conexão com o servidor caiu no meio da chamada.": microfone solto, cronometro parado, estado `erro`, bolinha vermelha e a comanda avisando que o pedido nao foi salvo. A tela nao tenta reconectar sozinha nem retomar a conversa |
| **Resposta que nao chega** | O relogio de 15 s dispara, escreve no log, mostra aviso **nao fatal** "O servidor demorou demais para responder. Pode falar de novo.", envia `{"tipo":"timeout"}` e reabre o microfone. A chamada continua |
| **`fim_audio` sem nenhum frame binario** | Nada para tocar: linha no log e o microfone reabre com motivo `"audio_vazio"`, **sem mandar frame nenhum**. Nao e timeout — o servidor respondeu, so mandou audio vazio — e nao e `resposta_tocada`, porque nada tocou |
| **Servidor esquece o `fim_audio`** | 800 ms depois do ultimo frame binario a tela fecha o arquivo sozinha e toca o que chegou |
| **Audio que falha ao tocar** (arquivo corrompido, formato que o navegador nao abre, reproducao bloqueada) | O `onerror` e o `catch` do `play()` escrevem no log ("não consegui tocar a resposta do servidor" / "o navegador não deixou tocar a resposta: ...") e reabrem o microfone com motivo `"falha_audio"`, para a chamada nao morrer em silencio. Nenhum frame sai: o servidor nao recebe `resposta_tocada` por um audio que o cliente nao ouviu. Limitacao assumida: ele tambem nao fica sabendo que a falha aconteceu, porque o protocolo nao tem frame para isso (ver PRO-01) |
| **Duas respostas em sequencia rapida** | Trocar o `src` rejeita a `play()` anterior com `AbortError`; o numero `idFala` faz a fala antiga ser ignorada, e so a atual reabre o microfone |
| **Servidor pede `ouvindo` com a resposta tocando** | Ignorado, com linha no log. O meia-duplex vence. Vale tambem enquanto os frames do audio de resposta estao chegando (`esperandoAudio`), nao so durante a reproducao: o `audio_resposta` ja fecha o microfone e poe a tela em `processando` |
| **Qualquer mensagem de estado depois do fim da chamada** | `aplicarEtapa` recusa tudo que chega fora de chamada, com linha no log. Sem isso, um `estado: ouvindo` que caisse na janela de 1,2 s do `chamada_encerrada` poria a tela de volta em "Pode falar" com o gravador ja parado e o microfone solto |
| **Cliente fala sem parar** | 15 s de fala continua fecham o turno a forca, com registro no log |
| **Ligar e desligar varias vezes** | Cada `ligar()` zera conversa, comanda, etapas, contador de turno, cronometro do turno (`tempoInicioTurno`, senao a chamada nova imprimiria o tempo do turno da chamada anterior), `protocoloNovo`, os pedacos de audio e o estado da deteccao de fala; cada `encerrar()` para gravador, trilhas, medidor, `AudioContext` e cronometro. O fechamento proposital marca `fechamosOSocket`, entao o `onclose` **nao** mostra "a conexão caiu"; a URL do audio de resposta anterior e revogada antes de criar a proxima |
| **Desligar e religar durante os 1,2 s do `chamada_encerrada`** | O resumo atrasado nao abre por cima da chamada nova: a tela so abre o resumo se o estado ainda for `encerrada` |
| **Esc com o resumo aberto** | Fecha o resumo. A chamada ja acabou; nada mais e afetado |

Vazamento conhecido e pequeno: o `URL.createObjectURL` do player da ultima gravacao (em `gravador.onstop`) nunca e revogado, entao cada chamada deixa um Blob na memoria da aba ate a pagina ser recarregada. O do audio de resposta, esse sim, e revogado a cada nova fala.

Nada disso foi medido nem testado de forma automatizada: nao existe teste de interface no repositorio, e os caminhos que dependem de mensagem do servidor (`transcricao`, `audio_resposta`, `pedido`, `pedido_salvo`, `chamada_encerrada`) nunca foram exercitados de ponta a ponta, porque o servidor nao envia nenhuma delas.

## Fora de escopo

- **Celular e telefonia real.** Nao ha aplicativo, nao ha ligacao por linha telefonica, nao ha numero para discar. O escopo deste semestre e chamada simulada, em desktop, no navegador. O CSS tem quebras em 1180px, 980px e 760px, mas o desenho e o teste foram feitos para desktop, e nenhum aparelho real foi usado.
- **Modo demonstracao.** Existiu e **foi removido a pedido do usuario**. Nao ha mais nenhum simulador, nenhuma resposta gravada, nenhum pedido de exemplo e nenhum atalho para ver a tela "funcionando". A consequencia, com todas as letras: **enquanto o VOZ-01 nao existir, a tela conecta, abre o microfone, grava e nao recebe resposta nenhuma — nao ha como demonstra-la funcionando.** O que da para mostrar hoje e a captura (o log enchendo de `"chunk guardado no backend!"`, as barrinhas reagindo a voz, o arquivo aparecendo no player do painel tecnico) e os estados que nao dependem do servidor: ocioso, conectando, ouvindo, encerrada e erro. Transcricao, etapas acendendo, comanda se preenchendo, voz do atendente e resumo com numero de pedido ficam inertes ate PRO-01 e VOZ-01 entregarem.
- **Interrupcao do atendente pelo cliente.** O meia-duplex impede por construcao.
- **Tela administrativa, lista de pedidos, login, cadastro por formulario e historico de chamadas.** Nao existem no projeto.
- **Escolha do microfone, controle de volume e ajuste de sensibilidade.** A tela usa o dispositivo padrao do sistema e limiares fixos.
- **Transcricao, modelo de linguagem, sintese e orquestracao:** VOZ-01.
- **Formato dos frames, nomes dos campos, ordem das mensagens e versao do protocolo:** PRO-01.
- **Cardapio, validacao de item, total e gravacao do pedido:** PED-01. A tela desenha o que recebe; ela nao monta pedido, so calcula o subtotal de cada linha.
- **Identificacao do cliente e CPF:** CLI-01.
- **Medicao de latencia, WER, acerto de extracao e de intencao, e verificacao de contraste e de leitor de tela:** MED-01.

## Questoes em aberto

**O RNF03 promete "interface responsiva, com prioridade para dispositivos moveis" e a entrega e desktop.** A tela nao e hostil ao celular — o layout colapsa em uma coluna com a chamada em cima e a comanda embaixo, a tira de etapas perde uma coluna abaixo de 980px e vira 2x2 abaixo de 760px, e os alvos de clique ja tem 48px ou mais —, mas ela foi desenhada para 1280x800, com `body` em `overflow: hidden`, e nunca foi aberta num aparelho real. Alem disso, o meia-duplex fica pior no celular: com o alto-falante do aparelho ligado, o retorno da voz sintetizada chega mais forte ao microfone do que num PC com caixa externa, e sem fone a conversa depende inteiramente de o microfone fechar na hora certa.
Recomendacao: levar a decisao para a professora junto com a do RF01, tratando as duas como uma coisa so, porque a redacao e a mesma promessa. Se o documento oficial for ajustado, trocar "com prioridade para dispositivos moveis" por "responsiva, com entrega e teste em desktop", que e o que o codigo faz. Se o texto for mantido, o minimo honesto e abrir a tela em um celular real, registrar o resultado com captura de tela em MED-01 e declarar na banca que o ajuste fino e a demonstracao sao em desktop. Fingir que colapsar em tela estreita e o mesmo que entregar para celular e o caminho que a banca derruba.

**A tela escreve "meta: 5 s" e essa meta nao existe.** O RNF01 diz explicitamente que a meta sera definida apos teste no hardware alvo, e nenhuma medicao foi feita; o numero esta fixo no `index.html`.
Recomendacao: trocar por "meta: a definir" ate MED-01 medir o piso das tres etapas na maquina alvo, e so entao escrever o numero real. Numero inventado na tela e exatamente o tipo de coisa que a banca pergunta de onde saiu.

**Quem decide o fim da fala: a tela ou o servidor?** Hoje decide a tela, por RMS, com limiares escritos a mao (0,05 para fala, 1,2 s de silencio para fechar o turno) e nunca calibrados. Microfone fraco ou cliente que fala baixo pode nunca cruzar 0,05, e o turno nao fecharia nunca; microfone de notebook em ambiente barulhento pode cruzar 0,05 so com ruido, e o turno fecharia sem ninguem ter falado. VOZ-01 preve deteccao de atividade de voz no servidor, que nao existe.
Recomendacao: manter o detector da tela como caminho de reserva e como comando explicito — ele e barato e ja funciona — e, quando o VAD do servidor existir, deixar o servidor mandar a etapa e a tela obedecer, que e o que `aplicarEtapa` ja faz. Antes disso, calibrar os dois limiares com gravacao real de pelo menos dois microfones diferentes e registrar os valores em MED-01.

**A chave do formato do audio.** Chegou a nao casar entre as duas pontas: a tela enviava `formato_audio` e o `backend/main.py` lia `controle.get("formato")`, guardando `None`. Ja corrigido no servidor, que passou a ler `formato_audio`. PRO-01 e o documento que fixa o nome do campo.
Recomendacao: nao mudar um lado sem mudar o outro no mesmo commit.

**A tela nao tenta reconectar.** Queda de WebSocket no meio da chamada vira erro fatal e o cliente precisa clicar de novo; nenhum contexto de conversa sobrevive, o que e coerente com VOZ-01 ("conexao cai no meio do turno: o cliente recomeca"), mas para o cliente parece a chamada simplesmente morrer.
Recomendacao: manter assim neste semestre — reconectar sem retomar o contexto daria a impressao falsa de que a conversa continua de onde parou — e deixar o texto da tarja explicito, dizendo que a chamada precisa ser reiniciada. Retomada de conversa so faz sentido depois que o servidor guardar estado de sessao, o que nao esta previsto.
