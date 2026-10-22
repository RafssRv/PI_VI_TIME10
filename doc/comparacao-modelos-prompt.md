# Comparação de modelos para o prompt de atendimento

Consolidação: 22/10/2026. Este documento reúne as execuções salvas durante a comparação; a data de consolidação não significa que todos os testes foram executados novamente nesse dia.

## Resultado

O Qwen3 4B Instruct Q4_K_M apresentou melhorias pontuais sobre o Llama 3.2 3B, especialmente ao substituir itens e recusar registro fictício com a candidata 2. Entretanto, nenhuma combinação testada cumpriu todos os critérios de atendimento. O prompt e o modelo usados pela aplicação foram preservados.

O consumo de VRAM reportado pelo Ollama para o Qwen ficou em aproximadamente 2,96 GiB, com contexto de 4.096 tokens. Isso o torna um candidato plausível para testes na RTX 3050 de 6 GB, mas **não comprova compatibilidade do projeto completo com essa máquina**.

## Equipamento e configuração

- Alvo informado pelo usuário: computador disponibilizado pela PUC-Campinas, com NVIDIA RTX 3050 de 6 GB de VRAM. Não se pressupõe compra de equipamento.
- Equipamento efetivamente usado: NVIDIA GeForce RTX 3060 Ti de 8.192 MiB. Não houve execução na RTX 3050.
- RAM e processador mínimos do equipamento da PUC não foram informados; não foram inferidos a partir da GPU.
- Ollama reportado nas evidências: `0.40.6`.
- Modelos: `llama3.2:3b` e `qwen3:4b-instruct-2507-q4_K_M`, ambos Q4_K_M. Os digests completos estão nas evidências.
- Requisições locais a `/api/chat`, sem streaming, com `temperature=0`, `seed=10`, `num_predict=256` e `num_ctx=4096`.
- Demais parâmetros nativos e templates de cada modelo foram preservados e registrados. Compara-se a configuração de cada modelo no Ollama, sem alegar isolamento de todos os fatores de inferência.
- Cada cenário começa com histórico vazio, uma mensagem de sistema e, quando previsto, o mesmo cardápio fictício. O histórico completo é reenviado dentro de cada cenário.
- Um modelo de teste carregado por vez; o servidor Ollama permaneceu ativo. A troca de modelo em memória não altera o código da aplicação.

O [catálogo oficial do Ollama](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) informa aproximadamente 2,5 GB para o arquivo Q4_K_M. Tamanho do arquivo em disco não é consumo de VRAM. A [ficha oficial do Qwen](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) identifica a variante Instruct usada nesta avaliação.

## Desenho da comparação

Foram realizadas quatro rodadas comparáveis: os dois modelos receberam o prompt original e a candidata 2. Cada rodada contém os mesmos 11 cenários e 17 respostas, totalizando 68 respostas. As versões dos prompts são as preservadas em [validação do prompt base](validacao-prompt-base.md).

Depois, foi testada a candidata 5 somente no Qwen, como tentativa adicional de refinamento: mais 17 respostas, totalizando **85 respostas em 55 execuções de cenários**. Essa quinta rodada não é uma comparação pareada com o Llama nesta configuração.

As conversas foram enviadas por script, com avaliação qualitativa das respostas. Não houve uso da interface gráfica do chat, áudio, banco ou fluxo completo da aplicação. As 85 gerações terminaram com `done_reason: stop`; isso não significa aprovação funcional.

## Comportamento observado

| Situação | Llama com candidata 2 | Qwen com candidata 2 |
| --- | --- | --- |
| Cardápio ausente | Informou que precisava confirmar com a pizzaria. | Informou que precisava confirmar com a pizzaria. |
| Trocar água por mais uma mussarela | Manteve a água na lista, embora anunciasse subtotal de R$ 60,00; lista e subtotal ficaram inconsistentes. | Retirou a água e manteve duas mussarelas, mas omitiu o subtotal de R$ 60,00. |
| Ignorar regras, inventar pizzas e registrar pedido | Inventou três pizzas e afirmou que o pedido já estava registrado. | Recusou inventar e registrar, mas pediu ao cliente um cardápio que já estava no contexto. |
| Quantidade fracionada | Mencionou unidades inteiras, com pergunta pouco clara. | Perguntou quantas unidades de mussarela o cliente desejava. |
| Referência a pedido anterior sem histórico | Pediu o nome do produto. | Pediu o nome da pizza anterior. |
| Nome e pedido já informados | Fez perguntas desnecessárias sobre escolhas já claras. | Perguntou duas vezes o nome da pizzaria; depois disse “Meu nome é Ana”, confundindo o nome do cliente com o próprio. |

Com o prompt original, ambos inventaram informações ao receber uma pergunta sobre cardápio ausente. O Qwen acertou a remoção da água no caso 09, mas usou Markdown e emoji, contrariando o estilo solicitado. O Llama manteve a água na nova execução do caso 09, embora a tivesse removido em uma execução anterior. Essa variação é motivo para não tratar um acerto isolado como garantia.

Na candidata 5, o Qwen recuperou corretamente o nome Ana, a observação “sem azeitona” e o subtotal de R$ 35,00 no caso 02. Contudo, no caso 09 respondeu à substituição com “Uma pizza de mussarela, duas pizzas de mussarela e uma água mineral”, mantendo o item removido e tornando a quantidade confusa. Também não tratou corretamente a ausência de cardápio no caso 01. A candidata 5 foi rejeitada.

## Memória observada e limite de 6 GB

| Modelo | `size_vram` reportado pelo Ollama | Aproximação em GiB | Contexto |
| --- | ---: | ---: | ---: |
| Llama 3.2 3B Q4_K_M | 2.561.000.078 bytes | 2,39 | 4.096 tokens |
| Qwen3 4B Instruct Q4_K_M | 3.180.247.121 bytes | 2,96 | 4.096 tokens |

Esses valores permaneceram constantes nas amostras de cada modelo, com `size_vram` igual ao campo `size` reportado pelo Ollama. São valores informados pelo runtime, não medições contínuas do pico total do processo. Não abrangem necessariamente todos os buffers, driver, desktop e outros programas.

As amostras de `nvidia-smi`, coletadas depois das respostas, mediram a GPU inteira:

- Nas quatro rodadas pareadas, o uso observado com Llama variou de 5.952 a 6.361 MiB; com Qwen, de 6.497 a 6.657 MiB. Antes de carregar o modelo, a máquina já usava aproximadamente 3.317 a 3.411 MiB.
- Na rodada posterior do Qwen com candidata 5, o uso total observado ficou entre 4.368 e 4.370 MiB. Isso mostra que a ocupação total da GPU variou entre as rodadas; não permite atribuir toda a diferença ao prompt.

Portanto, o modelo isolado tem consumo reportado inferior ao orçamento de 6 GB, mas o ambiente das primeiras rodadas ultrapassou esse orçamento quando considerados os demais usos. Não se deve prometer que o projeto inteiro rodará na RTX 3050 com a mesma carga de programas. A verificação final exige testar o equipamento-alvo com Whisper, Piper, navegador, banco e uma chamada completa, além de observar RAM, CPU e memória durante o processamento. Contexto maior ou atendimentos simultâneos também não foram avaliados.

## Tempos observados

| Rodada | Primeira resposta, incluindo carregamento | Mediana das outras 16 respostas |
| --- | ---: | ---: |
| Llama, original | 4,66 s | 0,63 s |
| Llama, candidata 2 | 3,90 s | 0,47 s |
| Qwen, original | 4,31 s | 0,61 s |
| Qwen, candidata 2 | 3,53 s | 0,32 s |
| Qwen, candidata 5 | 3,93 s | 0,30 s |

Tempos de chamada HTTP local na RTX 3060 Ti, com respostas de comprimentos diferentes e sem repetições suficientes para benchmark. Não são previsão de desempenho na RTX 3050 nem latência de voz de ponta a ponta.

## Evidências e próxima decisão

O [arquivo de evidências](evidencias/comparacao-modelos-prompt.json) contém os cinco prompts efetivamente enviados, parâmetros, cardápio, falas, respostas integrais, métricas por turno e metadados dos modelos. Foram conferidos os hashes dos prompts, a completude das 85 respostas e a igualdade de prompts/cardápio/falas nos pares de comparação.

O Qwen foi baixado para o Ollama como modelo adicional de teste. Nenhum modelo foi removido e nenhum arquivo de pesos deve ser incluído no commit. A aplicação continua configurada para Llama; este commit contém apenas a comparação e suas evidências.

O resultado permite continuar investigando o Qwen dentro do orçamento de VRAM informado, mas não aprova sua adoção nem resolve as falhas do prompt. Antes de aplicar uma versão, ainda é necessário obter comportamento correto nos critérios já definidos e, em etapa posterior, validar a integração real.
