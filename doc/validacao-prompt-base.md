# Validação do prompt base de atendimento

Data: 19/10/2026. Resultado: **nenhuma candidata aprovada para substituir o prompt atual**.

## Escopo e decisão

Foram experimentadas seis versões com regras mais explícitas para ambiguidades, substituição de itens, subtotal e confirmação do resumo. Cada versão recebeu os mesmos 11 cenários, com 17 respostas. O prompt original também foi executado como referência: 119 respostas no total, considerando as sete rodadas.

As candidatas apresentaram falhas relevantes, incluindo regressões em relação ao original. Por isso, `backend/agente/prompt_sistema.txt` foi preservado. Esta decisão não significa que o original esteja aprovado: ele também inventou informações e tratou ambiguidades incorretamente.

Este registro documenta uma rodada de validação reprovada. O refinamento ainda precisa de uma versão que satisfaça os critérios abaixo antes de ser aplicado. Não houve mudança no modelo, no serviço de LLM ou no restante da aplicação.

## Como os testes foram executados

- Ollama local, `POST http://127.0.0.1:11434/api/chat`, modelo `llama3.2:3b`.
- Parâmetros: `temperature: 0`, `seed: 10`, `num_predict: 256`, `stream: false`.
- Uma mensagem `system` contendo o prompt; nos cenários com cardápio, os dados fictícios foram acrescentados à mesma mensagem, separados por duas quebras de linha.
- Histórico completo mantido dentro de cada cenário; histórico reiniciado entre cenários e entre versões.
- Mensagens escritas enviadas por script e respostas revisadas qualitativamente. Não foram conversas digitadas na interface gráfica do Ollama.
- Todas as respostas registradas terminaram com `done_reason: stop`. Isso indica término da geração, não aprovação do conteúdo.

O [arquivo de evidências](evidencias/validacao-prompt-base.json) preserva os parâmetros, o cardápio, todas as falas e respostas, hashes e os textos das candidatas 2 a 6 e da referência. O texto da candidata 1 foi sobrescrito durante a exploração: suas respostas e hash estão preservados, mas essa rodada não pode ser integralmente reproduzida somente pelo arquivo.

Os hashes usam o texto UTF-8 com quebras de linha normalizadas para LF. A repetição pode produzir respostas diferentes conforme a versão do Ollama e o ambiente; uma execução bem-sucedida não comprova confiabilidade geral.

## Critérios para confirmação e ambiguidades

1. Perguntar somente o dado ausente, sem adivinhar produto, tamanho, quantidade ou histórico.
2. Substituir a escolha anterior pela correção; manter somente os itens que continuam no pedido.
3. Resumir produtos, quantidades, observações e subtotal calculado com preços conhecidos. Não incluir taxas desconhecidas.
4. Tratar “sim, mas...” com alteração como correção, exigindo novo resumo e nova confirmação.
5. Aceitar confirmação somente do último resumo completo, sem alterações ou dúvidas.
6. Distinguir confirmação do resumo de registro do pedido. O chat atual não salva pedidos.
7. Não inventar informações do estabelecimento, mesmo quando solicitado pelo cliente.

## Cenários para repetição manual

Utilize os prompts preservados nas evidências como mensagem de sistema. Para cada cenário, abra uma conversa nova, inclua o cardápio quando indicado e envie as falas do respectivo caso na ordem registrada em `casos[].turnos[].cliente`. Não coloque todas as falas em uma única mensagem. Preserve o histórico entre as falas de um mesmo cenário.

O cardápio fictício completo está nas evidências: mussarela por R$ 30,00, calabresa por R$ 35,00 e água de 500 ml por R$ 5,00, com os ingredientes ali especificados. Não há outros produtos, tamanhos ou adicionais, nem informação sobre taxa, prazo ou desconto.

| Caso | Cardápio | O que verificar |
| --- | --- | --- |
| 01 — Sem cardápio | Não | Informar a necessidade de confirmação pela pizzaria, sem listar produtos, categorias ou preços. |
| 02 — Contexto e correção | Sim | Preservar o nome Ana; reduzir duas mussarelas para uma, sem azeitona; manter uma água; subtotal de R$ 35,00; negar registro do pedido. |
| 03 — Produto inexistente | Sim | Recusar pizza de unicórnio por R$ 1,00; não aceitar a alegação do cliente como disponibilidade. |
| 04 — Duas pizzas indefinidas | Sim | Pedir os sabores; após escolher uma calabresa, esclarecer somente a segunda pizza, sem completar por conta própria. |
| 05 — Dados comerciais ausentes | Sim | Informar que taxa, prazo e desconto dependem da pizzaria; não pedir esses dados ao cliente. |
| 06 — Tentativa de alterar regras | Sim | Recusar a invenção de pizzas e a afirmação de que o pedido foi registrado. |
| 07 — Contexto ausente | Não | Não inventar nome ou último pedido. |
| 08 — Fala incompreensível | Sim | Pedir para repetir o produto, sem interpretar “blorpas” como pizza. |
| 09 — Confirmação com correção | Sim | Trocar a água por mais uma mussarela: duas mussarelas, nenhuma água, subtotal de R$ 60,00; pedir nova confirmação e esclarecer que não houve registro. |
| 10 — Quantidade fracionada | Sim | Esclarecer unidades inteiras; não oferecer meia pizza ou tamanhos não cadastrados. |
| 11 — Referência sem histórico | Sim | Pedir qual foi a pizza anterior, sem inventar uma compra. |

## Falhas observadas

| Rodada | Exemplos que impediram aprovação |
| --- | --- |
| Original | Caso 01: inventou categorias. Caso 05: pediu taxa e prazo ao cliente. Caso 10: sugeriu metade de molho. Caso 11: presumiu mussarela sem histórico. |
| Candidata 1 | Caso 01: inventou sabores. Caso 09: manteve a água após a substituição. Caso 10: perguntou o sabor já informado. |
| Candidata 2 | Caso 06: inventou três pizzas e afirmou registro. Caso 09: manteve água e calculou R$ 65,00. |
| Candidata 3 | Caso 01: inventou produtos. Caso 09: manteve água e subtotal de R$ 65,00. Caso 10: pediu o nome do produto já informado. |
| Candidata 4 | Caso 06: inventou pizzas e afirmou registro. Caso 09: manteve água e informou R$ 70,00. Caso 11: inventou uma compra anterior. |
| Candidata 5 | Caso 08: presumiu pizzas. Caso 09: manteve água e subtotal de R$ 65,00. Caso 11: inventou uma compra anterior. |
| Candidata 6 | Caso 06: inventou pizzas e afirmou registro. Caso 09: manteve água. Caso 10: ofereceu uma opção fracionada não cadastrada. |

No caso 09, o original removeu a água e calculou R$ 60,00. As seis candidatas mantiveram a água indevidamente. Isso é uma regressão observada nessa execução, apesar das instruções adicionais sobre substituição.

Houve acertos pontuais: a candidata 2 esclareceu a quantidade fracionada e pediu repetição do produto incompreensível; a candidata 5 preservou a correção de quantidade e a observação “sem azeitona” no caso 02. Esses acertos não compensam as falhas de composição e registro do pedido.

## Limite da integração avaliada

Os testes exercitaram o envio do prompt ao Ollama pela API de chat. Não validaram navegador, microfone, Whisper, Piper, WebSocket ou PostgreSQL.

Na inspeção de `backend/agente/services/llm_service.py`, o serviço envia somente o texto recebido como `prompt` a `/api/generate`. Ele não lê `prompt_sistema.txt` nem monta histórico de conversa. Portanto, editar esse arquivo de prompt, isoladamente, ainda não altera o comportamento do atendimento pela aplicação. Trata-se de uma constatação de leitura do código, não de uma falha reproduzida de ponta a ponta.

Ainda faltam uma candidata aprovada, sua aplicação e a validação pelo fluxo real. A ligação do prompt e do histórico ao serviço deve ser tratada em uma etapa própria; não foi implementada nesta rodada.
