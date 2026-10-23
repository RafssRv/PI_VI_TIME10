# Revisão do prompt a partir dos erros reais — Nonato

Data: 23/10/2026. **Resultado: três candidatas reprovadas. O prompt anterior foi restaurado.** Não houve correção funcional aprovada nem mudança de modelo ou da arquitetura.

## Evidências revisadas

Foram usados os oito cenários de [testes iniciais](testes-prompt-inicial.md) e os três casos adicionais de [validação do prompt](validacao-prompt-base.md). Esses registros são a referência disponível para as Fases 1 e 2; o repositório não os identifica formalmente com esses nomes. Também foi lido o diagnóstico integrado de 23/10: troca que manteve água e observações que produziram três pizzas em vez de duas.

| Erro observado | Regra ou exemplo experimentado |
| --- | --- |
| Categorias, popularidade e histórico inventados | Usar somente contexto do estabelecimento; não inferir compras anteriores. |
| Produto inexistente e preço alegado pelo cliente | Não tratar a fala do cliente como fonte de disponibilidade ou preço. |
| Perguntas sobre escolhas já claras | Aplicar exemplos somente quando a informação estiver realmente ausente. |
| Água mantida após troca | Exemplo concreto: uma mussarela e uma água, trocando água por mais uma mussarela, resulta em duas mussarelas e zero água. |
| Fração não permitida | “Uma pizza e meia de mussarela” exige esclarecer unidades inteiras, sem perguntar novamente o sabor. |
| Duas observações virando três pizzas | Duas unidades com observações diferentes continuam sendo duas unidades no total. |
| Prazo omitido | Responder separadamente aos dados solicitados: taxa, prazo e desconto. |

## Comportamento definido para transcrição ruim

As candidatas orientam o agente a preservar informações claras, perguntar somente o trecho duvidoso e não completar produtos, quantidades ou endereços por semelhança sonora. Um produto cadastrado não comprova que foi pedido. Exemplos: “duas [inaudível]” exige o produto; “uma pizza de...” exige o sabor; “duas ou três” exige a quantidade.

Texto incompreensível não autoriza confirmação. Depois de duas tentativas sem esclarecer, a orientação é pedir o dado por texto ou indicar o atendimento da pizzaria, sem alegar transferência. O modelo recebe texto e não deve alegar ter ouvido o áudio nem conhecer a confiança da transcrição.

Essas instruções estão preservadas integralmente nos prompts das candidatas nas [evidências](evidencias/erros-reais-prompt.json). **Não foram promovidas ao prompt em uso**, pois os testes abaixo mostraram regressões.

## Revalidação executada

Ollama local, `llama3.2:3b`, API `/api/chat`, `temperature=0`, `seed=10`, `num_predict=256`, sem streaming. Mesmo cardápio fictício, mesmas falas dos 11 cenários históricos, conversa nova por caso e histórico completo entre turnos. Contexto máximo não foi fixado; não foi capturada a versão/digest do runtime nesta rodada. São ensaios qualitativos, não benchmark.

Foram executadas cinco rodadas históricas de 17 respostas: referência atual, três candidatas e uma repetição acidental da candidata 2 após falha de edição no shell. Essa repetição tem o mesmo hash e respostas e não conta como uma quarta candidata. Cinco casos adicionais de transcrição, com oito respostas por rodada, foram executados com a referência e a candidata 1. Total preservado: **7 rodadas, 65 execuções de cenários e 101 respostas**.

| Versão | Resultado relevante |
| --- | --- |
| Referência atual | Manteve água na troca; aceitou fração; inventou compra anterior de mussarela; omitiu prazo. Recuperou Ana e subtotal de R$ 35,00. |
| Candidata 1 | Melhorou troca, fração, referência anterior e prazo. Regrediu na correção de quantidade: subtotal R$ 65,00 em vez de R$ 35,00. Omitiu subtotal da troca. |
| Candidata 2 | Manteve melhorias pontuais, mas atribuiu R$ 35,00 à mussarela e calculou subtotal R$ 40,00. Perguntou informações já conhecidas. |
| Candidata 3, mais curta | Recuperou R$ 35,00, mas perguntou o sabor da água; voltou a manter água na troca, omitir prazo e não esclarecer fração. |

Nos casos de transcrição, a candidata 1 preservou “duas unidades” ao perguntar o produto e perguntou o sabor de uma frase cortada. Entretanto, repetiu perguntas após duas tentativas inaudíveis, perguntou sabor quando a dúvida era quantidade e perguntou tamanho de uma água já definida. Nenhuma versão satisfez todos os critérios. Não houve áudio real, Whisper, interface, banco nem revalidação do modo integrado; a preservação interna do carrinho não pode ser comprovada por respostas textuais isoladas.

## Repetir e conferir

O executor usa o prompt e os parâmetros históricos da rodada selecionada; grava respostas sem atribuir aprovação automática. O caminho de saída deve ser novo. Exemplo com a candidata 1:

```powershell
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/revalidar_prompt.py doc/evidencias/erros-reais-prompt.json candidata1 .local-test/repeticao-candidata1.json
rtk proxy .venv/Scripts/python.exe -X utf8 scripts/validar_evidencias.py
```

Para os casos de transcrição, use `transcricao_candidata1` no lugar de `candidata1`. Compare cada resposta com `criterios_cenarios`, inclusive turnos intermediários, sem considerar `done_reason: stop` como aprovação. Os JSONs históricos anteriores foram preservados.

O executor também foi exercitado em uma repetição dos cinco casos de transcrição (oito respostas adicionais de verificação, fora das 101 catalogadas). O verificador de integridade aprovou os quatro arquivos de evidências. A suíte de evidências passou em sete testes; isso verifica os registros, não o comportamento do modelo.

## Pendência para concluir o objetivo

Adicionar regras e exemplos não bastou para corrigir o comportamento do modelo nesta configuração. Após três candidatas reprovadas, a decisão foi interromper ajustes sucessivos e preservar o prompt anterior. Para concluir a correção, é necessário decidir o próximo experimento: tratar pendências e alterações de pedido em código, ou comparar outra configuração de inferência/modelo com os mesmos critérios. Qualquer alternativa exige nova regressão e validação integrada antes de uso real.
