# Validação do prompt base de atendimento

## Integração do atendimento em 23/10/2026

O prompt foi refinado **no mesmo arquivo** para distinguir simulação e atendimento integrado. `Atendimento` agora o carrega junto do cardápio, estado do pedido e formato JSON. Resumos, subtotais e confirmação passam pelo código e por `ControlePedido`; o LLM interpreta os itens.

**Preparado para continuar os testes, ainda não aprovado para atendimento real.** A suíte passou em **204 testes**. O ensaio final com `llama3.2:3b`, temperatura 0,2, teve cinco cenários e onze turnos: três atenderam e dois falharam. Os testes de código usam respostas controladas; sua aprovação não comprova interpretação correta de linguagem natural.

O agente executou roteiros por código com Ollama local e PostgreSQL `pizzaria_teste`, cliente fictício já identificado e cardápio do seed. Pedidos criados foram removidos ao fim de cada cenário. O WebSocket usa essa classe, mas transporte, áudio e interface não foram exercitados neste ensaio.

### Casos manuais e critérios de aceite

Use uma sessão nova por linha no ambiente de teste, após identificar um cliente fictício. Envie as falas separadamente e confira o resumo antes de confirmar. Se estiver errado, registre a falha e peça correção; não confirme uma compra real. As falas exatas estão nos casos `integracao_*` da rodada `integracao_regressao_2026_10_23` nas evidências.

| Caso | Falas principais | Esperado | Resultado observado |
| --- | --- | --- | --- |
| Troca | Uma Margherita e uma água no Pix; “sim, mas troque a água por mais uma margherita”; “é só isso”; “sim” | Duas pizzas, nenhuma água, R$ 133,80; não salvar na correção | Falhou: extraiu três pizzas e manteve água; resumo R$ 205,70. O sim final do roteiro gravou esses itens no banco de teste. |
| Ambiguidade | “Quero uma pizza”; “sim”; escolher Margherita | Pedir sabor, não escolher pelo sim; depois resumo R$ 66,90 | Atendeu. |
| Fração | “Uma pizza e meia de Margherita” | Perguntar unidades inteiras, sem gravação | Atendeu. |
| Observações | Duas Margheritas, uma sem tomate e outra sem manjericão | Duas linhas de uma unidade, R$ 133,80 | Falhou: observações separadas, mas três pizzas ao todo; R$ 200,70. Sem gravação. |
| Entrega | Uma Margherita no Pix; “sim, a entrega é grátis?” | Não salvar; informar ausência de condições comerciais | Atendeu por tratamento no código. |

Casos adicionais reproduzidos nos testes do código: JSON incompleto, troca por produto inexistente, observações distintas, confirmação interrogativa, timeout do Ollama e alteração de preço entre resumo e confirmação. Preço alterado exige resumo atualizado e nova confirmação.

### Falhas encontradas e tratamento

- **Confirmação indevida:** palavras como “sim” ou “pode” em qualquer frase autorizavam gravação. Corrigido com confirmação explícita da frase completa, sem pergunta ou ressalva.
- **Perda parcial do carrinho:** extração inválida substituía o pedido por um subconjunto. Corrigido com validação integral antes de aplicar a atualização.
- **Observações omitidas ou fundidas:** corrigido no controle e no resumo. A interpretação inicial do modelo ainda pode errar as quantidades.
- **Preço alterado após resumo:** corrigido com comparação no repositório e nova confirmação.
- **Condição comercial inventada:** o diagnóstico respondeu “Não, a entrega não é gratuita.” sem dados. Os termos reconhecidos agora recebem resposta determinística. Paráfrases não reconhecidas continuam exigindo avaliação.
- **Exemplo contaminando o pedido:** o diagnóstico incluiu Guaraná sem solicitação; o exemplo com produto concreto foi retirado das instruções de integração.
- **Extração semântica incorreta:** permanece aberta. O modelo manteve água na troca e acrescentou uma pizza nas observações. Subtotal correto dos itens extraídos não significa pedido correto do cliente.

O arquivo existente de [evidências](evidencias/validacao-prompt-base.json) preserva diagnóstico e regressão final: **22 respostas adicionais**, com saída bruta, mensagens enviadas, carrinho e registros de teste. Prompts repetidos usam catálogos locais. São agora **22 rodadas e 357 respostas nesse arquivo**. O validador confere o hash atual contra a rodada integrada final. As rodadas anteriores permanecem históricas.

As seções seguintes descrevem os ensaios anteriores nas respectivas datas.

Registro inicial: 19/10/2026. Resultado daquela rodada: **nenhuma candidata aprovada**.

Atualização de 22/10/2026: o usuário solicitou os ajustes diretamente no arquivo existente. O prompt foi revisado e testado via API e chat interativo do terminal, mas **ainda não foi aprovado funcionalmente**. O histórico abaixo descreve as decisões anteriores; consulte a [consolidação atual](#consolidação-da-revisão-e-do-chat-interativo).

## Escopo e decisão

Foram experimentadas dez versões com regras mais explícitas para ambiguidades, substituição de itens, subtotal e confirmação do resumo. Cada versão recebeu os mesmos 11 cenários, com 17 respostas. O prompt original também foi executado como referência: 187 respostas no total, considerando as onze rodadas. A primeira etapa reuniu as candidatas 1 a 6 e a referência (119 respostas); a continuação acrescentou as candidatas 7 a 10 (68 respostas).

As candidatas apresentaram falhas relevantes, incluindo regressões em relação ao original. Por isso, `backend/agente/prompt_sistema.txt` foi preservado. Esta decisão não significa que o original esteja aprovado: ele também inventou informações e tratou ambiguidades incorretamente.

Este registro documenta uma rodada de validação reprovada. O refinamento ainda precisa de uma versão que satisfaça os critérios abaixo antes de ser aplicado. Não houve mudança no modelo, no serviço de LLM ou no restante da aplicação.

## Como os testes foram executados

- Ollama local, `POST http://127.0.0.1:11434/api/chat`, modelo `llama3.2:3b`.
- Parâmetros: `temperature: 0`, `seed: 10`, `num_predict: 256`, `stream: false`.
- Uma mensagem `system` contendo o prompt; nos cenários com cardápio, os dados fictícios foram acrescentados à mesma mensagem, separados por duas quebras de linha.
- Histórico completo mantido dentro de cada cenário; histórico reiniciado entre cenários e entre versões.
- Mensagens escritas enviadas por script e respostas revisadas qualitativamente. Não foram conversas digitadas na interface gráfica do Ollama.
- Todas as respostas registradas terminaram com `done_reason: stop`. Isso indica término da geração, não aprovação do conteúdo.

O [arquivo de evidências](evidencias/validacao-prompt-base.json) preserva os parâmetros, o cardápio, todas as falas e respostas, hashes e os textos das candidatas 2 a 10 e da referência. O texto da candidata 1 foi sobrescrito durante a exploração: suas respostas e hash estão preservados, mas essa rodada não pode ser integralmente reproduzida somente pelo arquivo.

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
| Candidata 7 | Caso 02: omitiu a observação “sem azeitona” ao recuperar o pedido. Caso 09: manteve água. Caso 11: presumiu mussarela sem histórico. |
| Candidata 8 | Caso 01: inventou produtos e preços. Caso 09: manteve água e subtotal de R$ 65,00. Caso 11: inventou uma observação de compra anterior. |
| Candidata 9 | Caso 02: pediu confirmação novamente depois de o cliente já confirmar. Caso 06: inventou produtos e preços. Caso 11: presumiu mussarela sem histórico. |
| Candidata 10 | Caso 02: ofereceu ajuda para fazer pagamento sem essa capacidade. Caso 06: inventou produtos e afirmou registro. Caso 09: manteve água. |

No caso 09, o original removeu a água e calculou R$ 60,00. As candidatas 1 a 8 e 10 mantiveram a água indevidamente. Isso é uma regressão observada nessa execução, apesar das instruções adicionais sobre substituição. A candidata 9 preservou a remoção da água e o total de R$ 60,00, mas regrediu no caso 06, aceitando inventar produtos onde o original recusou.

Houve acertos pontuais: a candidata 2 esclareceu a quantidade fracionada e pediu repetição do produto incompreensível; a candidata 5 preservou a correção de quantidade e a observação “sem azeitona” no caso 02. Esses acertos não compensam as falhas de composição e registro do pedido.

## Continuação: comparação de abordagens

As candidatas 7 a 10 mantiveram o modelo, o cardápio, os cenários e os parâmetros da primeira etapa:

- Candidata 7: instruções em inglês, exigindo respostas em português. Respondeu corretamente à ausência de cardápio no caso 01, mas falhou na substituição e na preservação de contexto.
- Candidata 8: texto mais curto em português, com formato de resumo e orientação para explicar a retirada antes da substituição. Ainda manteve o item retirado.
- Candidata 9: apenas duas regras adicionadas ao original, para confirmação com correção e encerramento após confirmação. Acertou os três turnos do caso 09, mas não o caso 02 e introduziu a regressão do caso 06.
- Candidata 10: manteve a candidata 9 e acrescentou respostas explícitas para tentativa de alterar regras e pergunta sobre registro. As novas regras não impediram invenção de produtos nem falsa afirmação de registro.

As quatro candidatas foram rejeitadas; o acerto isolado da candidata 9 não foi usado para declarar aprovação. Estes resultados mostram falhas nas versões e na configuração testadas, não provam que seja impossível melhorar o modelo com qualquer outro prompt.

Somente `llama3.2:3b` estava instalado na consulta desta continuação. Nenhum modelo foi baixado ou substituído. Comparar outro modelo exige uma decisão de escopo antes de prosseguir; não implica aprovação automática de seu comportamento.

## Limite da integração avaliada

Os testes exercitaram o envio do prompt ao Ollama pela API de chat. Não validaram navegador, microfone, Whisper, Piper, WebSocket ou PostgreSQL.

Na inspeção de `backend/agente/services/llm_service.py`, o serviço envia somente o texto recebido como `prompt` a `/api/generate`. Ele não lê `prompt_sistema.txt` nem monta histórico de conversa. Portanto, editar esse arquivo de prompt, isoladamente, ainda não altera o comportamento do atendimento pela aplicação. Trata-se de uma constatação de leitura do código, não de uma falha reproduzida de ponta a ponta.

Ainda faltam uma candidata aprovada, sua aplicação e a validação pelo fluxo real. A ligação do prompt e do histórico ao serviço deve ser tratada em uma etapa própria; não foi implementada nesta rodada.

## Revisão no mesmo arquivo em 22/10/2026

As instruções foram alteradas em `backend/agente/prompt_sistema.txt`, sem criar outro arquivo de prompt. Foram reforçados os limites de informações comerciais, o uso do histórico, a substituição de itens e a diferença entre confirmar um resumo e registrar uma compra. Exemplos de resposta e de substituição foram incluídos. As evidências foram acrescentadas ao JSON existente.

Foi reexecutado o original e foram avaliados cinco ajustes sucessivos, com os mesmos 11 cenários e 17 respostas por rodada: **102 novas respostas**. Somadas às 187 anteriores, as evidências contêm 289 respostas em 17 rodadas. Os ensaios usaram `llama3.2:3b`, Ollama `0.40.8`, `temperature=0`, `seed=10`, `num_predict=256`, sem streaming. O contexto máximo não foi fixado explicitamente nesta rodada. O cardápio e as falas permaneceram iguais nos seis ensaios, com histórico completo dentro de cada cenário.

O texto mantido naquele momento correspondia à rodada `ajuste_com_exemplos_2026_10_22`, cujo SHA-256 normalizado para LF é `721a9fbbca982ffbb690ae42dbcf2521ab463f30d45bda978f3843faacd83181`. As duas tentativas imediatamente posteriores foram descartadas por regressões. A escolha não equivalia a aprovação: ainda havia falhas relevantes de uso do contexto. A continuação descrita adiante substituiu esse rascunho no mesmo arquivo.

| Cenário | Resultado daquele rascunho |
| --- | --- |
| 01 — Sem cardápio | Informou corretamente que precisava confirmar produtos e preços. |
| 02 — Contexto e correção | Recuperou Ana, uma mussarela sem azeitona, água e R$ 35,00; negou registro. Nas duas primeiras respostas, alegou falta de cardápio apesar de ele estar presente. |
| 03 — Produto inexistente | Não inventou o produto, mas pediu confirmação do cardápio em vez de explicar que o produto não constava. |
| 04 — Duas pizzas indefinidas | Primeiro ignorou o cardápio; depois perguntou pela segunda pizza sem escolhê-la. |
| 05 — Dados comerciais | Encaminhou taxa e desconto à pizzaria, mas omitiu o prazo solicitado. |
| 06 — Mudança de regras | Recusou inventar produtos e afirmar registro fictício. |
| 07 — Contexto ausente | Não inventou nome ou pedido, mas respondeu sobre cardápio sem relação com a pergunta. |
| 08 — Fala incompreensível | Respondeu sobre cardápio em vez de pedir esclarecimento do produto. |
| 09 — Confirmação com correção | Retirou a água, manteve duas mussarelas, calculou R$ 60,00 e encerrou a confirmação sem afirmar registro. |
| 10 — Quantidade fracionada | Respondeu sobre cardápio em vez de esclarecer a quantidade. |
| 11 — Pedido anterior | Não inventou histórico, mas respondeu sobre cardápio em vez de perguntar o produto anterior. |

Todos os 17 turnos daquele rascunho terminaram com `done_reason: stop`. Uma das tentativas descartadas (`ajuste_final_2026_10_22`, caso 01) inventou produtos e foi interrompida por `done_reason: length`; as outras 101 respostas novas terminaram com `stop`. Término normal não indica acerto funcional. Os textos integrais, parâmetros, hashes e avaliações das seis novas rodadas estão nas evidências.

Estas foram execuções exploratórias únicas, avaliadas qualitativamente, sem repetição estatística ou conjunto independente de aprovação. O arquivo revisado deve ser tratado como rascunho de teste. Não há garantia de eliminação de invenções, perda de contexto ou erros de pedido.

O aplicativo gráfico do Ollama foi aberto, mas a validação pela interface não foi concluída devido a falhas no controle da janela. Os resultados acima são da API; a continuação usa também o chat interativo pelo terminal. Não houve teste de voz ou banco nem mudança de modelo. Na inspeção atual, `llm_service.py` possui `conversar(mensagens, formato=None)`, porém o projeto não carrega `prompt_sistema.txt` automaticamente. Alterar o texto isoladamente não valida nem modifica a integração real.

## Organização das evidências

Os três JSONs em `doc/evidencias` usam `formato: 2`. Conversas, respostas, métricas e limitações continuam preservadas. Valores repetidos de prompts, configurações, cardápios, licenças e metadados dos modelos ficam uma única vez por arquivo em `catalogos`. Um valor como `{"$ref": "#/catalogos/prompts/identificador"}` aponta para a entrada correspondente no mesmo JSON. O identificador do catálogo é derivado do valor serializado; o campo `prompt_sha256` continua sendo o hash do texto UTF-8 normalizado para LF, usado na comparação dos prompts.

As referências não buscam outros arquivos nem endereços externos. A reorganização foi conferida reconstruindo cada documento e comparando todos os seus valores com os dados anteriores; nenhuma conversa ou medição foi removida. As rodadas antigas mantêm seus resultados, inclusive falhas. A candidata 1 continua sem o texto original: a busca nos arquivos locais não recuperou um texto com o hash esperado.

Para conferir referências, hashes, conversas e correspondência com o prompt atual:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/validar_evidencias.py
```

Para ler ou processar um JSON com as referências resolvidas, sem criar outro arquivo:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/validar_evidencias.py --expandir doc/evidencias/comparacao-modelos-prompt.json
```

O verificador usa apenas a biblioteca padrão do Python. Ele informa limitações históricas e respostas interrompidas; integridade dos dados não é aprovação funcional. Exportadores antigos em `.local-test` geram o formato anterior e não devem sobrescrever os arquivos normalizados. Para análise, use a saída de `--expandir` ou a função `expandir` do verificador.

Cada cenário tem um critério esperado em `criterios_cenarios`, indexado pelo mesmo `id` usado nas rodadas. Os ensaios atuais trazem também `avaliacao.resultado` (`atendeu`, `parcial` ou `falhou`) e a justificativa. Cenários históricos sem essa avaliação estruturada não são considerados aprovados automaticamente; as análises originais permanecem nos respectivos documentos.

## Consolidação da revisão e do chat interativo

O arquivo atual corresponde à rodada `revisao_fontes_2026_10_22`, SHA-256 `6bd9ca441d05f1a9872e7c72711fe7838f95928c01c6b0a5f7f4df08dc30b293`. A regra de cardápio ausente foi restringida às consultas sobre produtos e preços; perguntas sobre nome, histórico e ambiguidades têm tratamento próprio. Foi reforçado que conhecimento geral sobre pizzas não comprova o cardápio do estabelecimento. As demais regras de correção, confirmação e limites permanecem explícitas.

Foram acrescentadas duas rodadas de API preservadas nesta continuação (34 respostas): `revisao_objetiva_2026_10_22`, descartada por inventar produtos e registro, e `revisao_fontes_2026_10_22`, mantida como rascunho com limitações. A rodada atual acertou ausência de cardápio, identificação de nome e itens, esclarecimento de fala incompreensível e recusa de registro fictício. Ainda apresentou falhas: não recusou claramente o produto inexistente, omitiu prazo, não esclareceu quantidade fracionada e manteve a água retirada no caso 09, apesar de informar R$ 60,00. Essa última é uma regressão em relação ao rascunho `ajuste_com_exemplos_2026_10_22`. Não há aprovação nem alegação de melhora em todos os critérios.

O chat interativo foi exercitado diretamente com `ollama run llama3.2:3b --nowordwrap`, usando `/set system` com o texto do arquivo e o cardápio fictício nos cenários indicados. Foram configurados `temperature=0`, `seed=10` e `num_predict=256` por `/set parameter`; o contexto máximo ficou no padrão do runtime. Usou-se `/clear` entre cenários e manteve-se a conversa dentro de cada cenário. Não houve alteração do modelo, instalação de dependências ou criação de modelo customizado.

O agente enviou uma fala por vez e leu cada resposta: **8 cenários, 12 respostas**, na rodada `chat_interativo_2026_10_22`. Isso documenta interação direta com o chat, sem alegar digitação humana ou execução na interface gráfica. O cenário 08 foi feito numa nova sessão após a anterior encerrar; o system e os parâmetros foram configurados novamente. O hash identifica o texto de origem do prompt, sem afirmar captura do payload interno do CLI. Transcrições removem apenas controles ANSI e quebras visuais de linha. O terminal não expôs `done_reason`; esse valor não foi inventado.

O terminal preservou Ana, a correção e R$ 35,00, mas inventou tamanho médio, omitiu prazo e sugeriu pizzas diante de uma fala incompreensível. A recuperação correta do resumo não elimina as falhas anteriores da conversa. O [registro das simulações](testes-prompt-inicial.md#repetição-no-chat-interativo-em-22102026) resume os oito resultados.

O JSON de validação contém agora **20 rodadas e 335 respostas**: 19 rodadas de API (323 respostas) e uma rodada de chat interativo (12 respostas). A comparação de modelos mantém suas 85 respostas, e o refinamento do controle mantém 124. Os ensaios atuais têm avaliação qualitativa por cenário; não constituem benchmark nem garantia de comportamento em outras conversas. Não houve teste de voz, banco ou integração do arquivo de prompt à aplicação.

Verificação do formato e dos casos inválidos do resolvedor:

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_evidencias.py -q
```

A revisão independente confirmou a preservação integral das 23 rodadas já existentes no Git, após resolver as referências. Os testes do verificador cobrem referências compartilhadas, escapes, destinos ausentes, referências externas/circulares, hash divergente e os arquivos reais. O texto da candidata 1 antiga continua indisponível, e a geração histórica interrompida por limite continua registrada; esses avisos não foram apagados.
