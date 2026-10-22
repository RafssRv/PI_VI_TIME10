# Controle do resumo do pedido em código

Entrega de 22/10/2026: controle em memória de itens, valores e confirmação, autorizado após os testes dos modelos. A ligação ao LLM, ao WebSocket e à gravação no banco fica para uma próxima etapa.

## O que mudou e por quê

O módulo `backend/agente/controle_pedido.py` recebe um cardápio confiável e operações explícitas. Ele mantém o pedido por conversa e gera o texto do resumo a partir dos itens e preços, sem pedir ao modelo que calcule ou reescreva valores.

- Inclusão, redução, remoção, troca total ou parcial e alteração de observações.
- Preços obtidos exclusivamente do cardápio fornecido pelo servidor. Operações não aceitam um preço escolhido pelo modelo.
- Valores calculados com `Decimal`; quantidades exigem inteiros positivos. Frações, booleanos e textos numéricos são recusados, sem conversão silenciosa.
- Produtos desconhecidos ou inativos são recusados. A resolução de nomes ambíguos continua sendo responsabilidade do chamador, antes de enviar um identificador ao controle.
- Trocas preservam itens não envolvidos e observações. Unidades do mesmo produto com observações diferentes permanecem separadas. Uma troca inválida preserva todos os itens anteriores, cria uma pendência e invalida a confirmação.
- Cada resumo tem um token próprio. A confirmação só aceita o token do resumo atual. Alterações ou dúvidas invalidam esse token e a confirmação anterior.
- Uma operação válida não apaga automaticamente outra dúvida pendente. Depois do esclarecimento explícito, é necessário apresentar um novo resumo.
- Desistência esvazia o resumo, sem afirmar cancelamento no banco. Confirmar o resumo também não registra a compra.

O cardápio é um retrato dos produtos recebidos na criação da conversa. Mudanças posteriores de preço/disponibilidade no banco precisam ser tratadas pela futura integração antes da gravação. O repositório existente continua responsável por validar e salvar pedidos; ele não foi substituído.

## Exemplo de uso

Execute com `backend` no caminho de importação, como ocorre ao iniciar a aplicação nessa pasta:

```python
from decimal import Decimal
from agente.controle_pedido import ControlePedido, ProdutoCardapio

controle = ControlePedido([
    ProdutoCardapio(1, "Pizza de Mussarela", Decimal("30.00")),
    ProdutoCardapio(2, "Água Mineral", Decimal("5.00")),
])
controle.adicionar(1, 1)
agua = controle.adicionar(2, 1)
primeiro = controle.resumir()
print(primeiro.texto)  # subtotal: R$ 35,00

# Cliente: "Sim, mas troque a água por mais uma pizza."
controle.substituir(agua, 1, 1, 1)
atual = controle.resumir()
print(atual.texto)  # duas pizzas, nenhuma água, subtotal: R$ 60,00

# Somente depois de apresentar o novo resumo e receber confirmação sem dúvidas:
print(controle.confirmar(atual.token))
# Resumo confirmado por você. O pedido ainda não foi registrado;
# a pizzaria precisa concluir o atendimento.
```

Crie uma instância por conversa. O servidor deve guardar o token do resumo realmente apresentado; o modelo não deve gerar nem escolher esse token. Em uma fala com confirmação e alteração, processe a alteração e peça nova confirmação. Em uma fala ambígua, use `definir_pendencia(pergunta)` e não confirme. Após esclarecer, use `definir_pendencia(None)`, apresente o resumo atualizado e só então receba a confirmação.

Este módulo não identifica a intenção de uma fala. Interpretar “sim, mas...” incorretamente ainda seria uma falha do adaptador que será implementado depois. Tampouco valida automaticamente se o cliente realmente ouviu ou leu o resumo: o chamador deve garantir esse vínculo. As garantias dos testes abaixo valem para operações estruturadas, não para toda conversa em linguagem natural.

## Verificação executada

Foram adicionados 39 testes em `tests/test_controle_pedido.py`, cobrindo as operações e os erros observados nos ensaios. Exemplos:

| Cenário | Resultado conferido pelo teste |
| --- | --- |
| Duas mussarelas e uma água | R$ 65,00. |
| Reduzir para uma mussarela sem azeitona, mantendo água | R$ 35,00, com observação preservada. |
| Trocar água por mais uma mussarela | Duas mussarelas, nenhuma água, R$ 60,00; confirmação antiga rejeitada. |
| Duas calabresas e três águas; trocar duas águas por mais uma calabresa | Três calabresas e uma água, R$ 110,00. |
| Acrescentar duas águas a uma calabresa sem cebola | R$ 45,00 e solicitação sem cebola preservada. |
| Trocar por produto inexistente | Itens anteriores preservados; pendência bloqueia resumo e confirmação. |
| Perguntar se o subtotal inclui entrega | Pendência bloqueia confirmação; nenhuma taxa é inventada. |
| Desistir de todos os itens | Resumo vazio e confirmação invalidada, sem registro ou cancelamento no banco. |
| Usar token de outra conversa ou de resumo antigo | Confirmação recusada. |

Execução isolada, sem Ollama, GPU ou PostgreSQL:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_controle_pedido.py -q
```

Resultado: **39 passaram**. A preparação do banco em `tests/conftest.py` deixou de ser automática para todos os testes; continua sendo solicitada pela fixture `db`. Isso permite testar o controle em memória sem PostgreSQL.

A suíte completa também foi executada com o PostgreSQL temporário da pasta `.local-test`, na porta 55432. O `conftest.py` direciona os testes para `pizzaria_teste`, separado do banco de desenvolvimento. Resultado: **139 passaram**, incluindo os 100 testes existentes.

Não houve teste do pipeline de voz nesta entrega. O serviço de LLM continua usando a configuração anterior, e o prompt em uso não foi substituído por uma candidata reprovada.

## Ensaios que motivaram o controle

Nesta rodada, foram avaliadas quatro candidatas adicionais no Qwen (versões 11 a 14), sete cenários novos nas versões 13 e 14 e o Gemma 3 4B Q4_K_M com a versão 14 nos 18 cenários. São **124 respostas**, preservadas nas [evidências do refinamento](evidencias/refinamento-controle-pedido.json), com prompts, parâmetros, falas, respostas e métricas. Os cenários adicionais eram novos na primeira execução da versão 13; foram usados como regressão na versão 14, não como uma segunda validação independente.

Falhas relevantes:

- Qwen v11: informou R$ 95,00 para duas mussarelas e uma água, cujo subtotal era R$ 65,00.
- Qwen v12: omitiu subtotais nos resumos do caso de substituição.
- Qwen v13: acertou a troca total da água por pizza, mas errou a troca parcial das águas e confundiu a dúvida sobre quantidade com uma dúvida sobre produto.
- Qwen v14: acertou a troca parcial, mas inventou o nome João quando não havia nome no histórico e deixou de informar valores em algumas respostas.
- Gemma v14: calculou R$ 90,00 em vez de R$ 65,00 no primeiro pedido e afirmou registro fictício quando solicitado a ignorar regras.

Nenhuma dessas candidatas foi aplicada ao prompt da aplicação. A correção entregue é o controle testado em código, que ainda precisará ser chamado pelo fluxo de atendimento.

O [Gemma usado](https://ollama.com/library/gemma3:4b-it-q4_K_M) foi baixado como modelo adicional de teste. Com contexto de 4.096 tokens e somente texto, o Ollama reportou 2.882.482.994 bytes de VRAM (aproximadamente 2,68 GiB); as amostras da GPU inteira ficaram entre 4.489 e 4.491 MiB, na RTX 3060 Ti. Esses valores não são garantia de pico de memória ou de funcionamento do projeto completo na RTX 3050. Nenhum modelo foi substituído na aplicação.
