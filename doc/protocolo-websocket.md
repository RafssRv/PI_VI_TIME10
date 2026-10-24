# Protocolo WebSocket de voz — versão 1

Endpoint: `/ws/falar`. Mensagens de texto contêm objetos JSON; mensagens
binárias contêm blocos do áudio gravado pelo navegador. O contrato de entrada
é validado por `backend/protocolo.py`; o ciclo da conexão fica em `backend/rotas/voz.py`.

## Abertura e encerramento

1. O servidor aceita a conexão e envia `{"tipo":"pronto","versao_protocolo":1}`.
2. O cliente envia `iniciar_chamada`, antes de qualquer áudio.
3. O cliente envia blocos binários enquanto está ouvindo o usuário.
4. Ao terminar uma fala, envia `fim_da_fala` e pausa a captura durante a resposta.
5. Ao terminar a reprodução, envia `resposta_tocada` e retoma a captura.
6. Para desligar, envia `encerrar_chamada` ou fecha o WebSocket.

O frontend guarda os blocos capturados antes de `pronto` e os envia após
`iniciar_chamada`, na ordem original, preservando o cabeçalho do áudio.
A página de diagnóstico `/teste` (somente com `AMBIENTE=dev`) também envia a abertura, mas só grava blocos;
ela não detecta fim de fala nem executa turnos por conta própria.

## Mensagens do cliente

Os campos listados são obrigatórios. Campos extras, tipos desconhecidos e
valores de tipo incorreto são rejeitados. Booleanos e strings numéricas não
substituem inteiros.

| Tipo | Campos além de `tipo` | Validação |
| --- | --- | --- |
| `iniciar_chamada` | `versao_protocolo`, `formato_audio`, `chunk_ms` | Versão inteira `1`; formato aceito abaixo; intervalo inteiro entre 1 e 10.000 ms. Apenas uma abertura por conexão. |
| `fim_da_fala` | `turno`, `duracao_ms` | Turno inteiro positivo até 2³¹−1, maior que o último processado; deve haver áudio novo. Duração declarada inteira entre 1 e 900.000 ms. |
| `resposta_tocada` | `turno` | Turno inteiro positivo que não ultrapasse o último processado. Avisos atrasados são aceitos. |
| `timeout` | `turno` | Mesma validação de `resposta_tocada`. É um aviso do navegador, sem cancelamento ou reexecução do pedido. |
| `encerrar_chamada` | `motivo` | Texto não vazio com até 80 caracteres. Pode ser enviado antes da abertura, para desistir da conexão. |

Formatos aceitos: `audio/webm`, `audio/webm;codecs=opus`, `audio/ogg`,
`audio/ogg;codecs=opus`, `audio/mp4` e `audio/mp4;codecs=mp4a.40.2`.
A comparação ignora maiúsculas e espaços. O formato declarado não substitui
a decodificação efetiva do áudio pelo serviço de voz.

Exemplo de abertura:

```json
{"tipo":"iniciar_chamada","versao_protocolo":1,"formato_audio":"audio/webm;codecs=opus","chunk_ms":250}
```

Exemplo de fim de fala:

```json
{"tipo":"fim_da_fala","turno":1,"duracao_ms":2100}
```

## Limites por conexão

| Recurso | Limite |
| --- | --- |
| Mensagem JSON de controle, codificada em UTF-8 | 4 KiB (4.096 bytes) |
| Mensagem binária de áudio | 1 MiB (1.048.576 bytes) |
| Soma dos blocos de áudio recebidos | 20 MiB (20.971.520 bytes) |
| Prazo para recebimento de novos dados, desde a aceitação | 15 minutos |

Os limites são constantes em `backend/protocolo.py`. O tamanho é verificado
antes de escrever o bloco no arquivo de diagnóstico ou acrescentá-lo ao buffer
da chamada. O acumulado não é zerado entre turnos; uma segunda abertura não
reinicia os limites. Tamanhos exatamente no limite são aceitos.

O prazo usa o relógio monotônico do servidor, incluindo tempo ocioso e de
processamento. `duracao_ms` e `chunk_ms` enviados pelo cliente não controlam
esse relógio. Uma conexão ociosa também expira, sem depender de novos frames.

Se o prazo vencer durante um turno, o servidor deixa esse turno terminar e
encerra a recepção antes de admitir outro frame. Isso evita interromper uma
gravação de pedido no banco. **Não é um timeout de execução do Whisper,
Ollama ou Piper**: uma etapa travada ainda depende dos limites do próprio
serviço. Esses limites também não restringem a soma de conexões simultâneas
nem o tamanho do áudio depois de descompactado.

## Respostas do servidor

| Tipo | Conteúdo |
| --- | --- |
| `pronto` | `versao_protocolo: 1` |
| `estado` | `etapa` (`transcrevendo`, `pensando`, `respondendo` ou `ouvindo`) e, quando disponível, `turno` |
| `transcricao` | `turno`, `quem` (`cliente` ou `atendente`), `texto`, `parcial: false` |
| `pedido` | `turno`, `pedido_id` (número ou `null`), `cliente`, `itens`, `total`, `forma_pagamento`, `endereco_entrega` |
| `pedido_salvo` | `turno`, `pedido_id`, `total`, somente depois da persistência |
| `audio_resposta` | `turno`, `formato: "audio/wav"`; seguido do áudio binário |
| `fim_audio` | Marca o fim dos blocos de resposta |
| `erro` | `onde`, `mensagem`, `fatal` |

Dinheiro é enviado como string decimal com duas casas. Cada item de `pedido`
contém `produto`, `quantidade`, `preco_unitario` e `observacao`. `cliente`
contém nome e telefone, sem CPF. O pedido é plano: não existe uma chave
intermediária `pedido` dentro da mensagem.

A comanda salva permanece após limpar o carrinho ou agradecer. Um novo
rascunho tem `pedido_id: null`. A confirmação é enviada antes da síntese,
portanto uma falha de voz não esconde um pedido que já foi registrado.

O servidor ainda envia o texto simples `chunk guardado no backend!` como
confirmação de recebimento de áudio; o frontend o trata apenas como log.
`chamada_encerrada` é compreendido pelo frontend, mas esta rota não o emite.

## Rejeições

Uma entrada inválida encerra apenas aquela conexão. Antes de fechar, o
servidor envia uma mensagem como:

```json
{"tipo":"erro","onde":"protocolo","mensagem":"Envie iniciar_chamada antes do áudio.","fatal":true}
```

- Código WebSocket `1008`: JSON inválido, violação de campos/sequência ou prazo vencido.
- Código `1009`: limite de bytes ultrapassado.
- Código `1000`: encerramento normal solicitado pelo cliente.
- Código `1011`: falha inesperada no processamento da chamada; evento de
  erro com `onde: "servidor"` e mensagem genérica, quando a conexão permite enviar.

As mensagens de rejeição não reproduzem o conteúdo recebido. O frontend
exibe o erro fatal e encerra a captura. A confirmação de uma venda já salva
continua válida, mesmo que a conexão termine depois.

Erros de áudio, transcrição, atendimento e síntese também usam mensagens
fixas, sem texto de exceções. A política de diagnóstico está em
`logs-e-privacidade.md`.

## Verificação

`python -m pytest tests/test_websocket.py -q` verifica o handler com frames
ASGI e o WebSocket real do Starlette, simulando apenas o pipeline de voz.
`npm run teste:frontend` verifica a ordem de abertura/áudio e a comanda com
DOM e microfone simulados. A suíte Python completa continua em `npm run teste`.
