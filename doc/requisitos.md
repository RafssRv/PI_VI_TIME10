# Requisitos

Os 26 requisitos abaixo vêm do documento oficial do Projeto Integrador VI (11 funcionais, 6 não funcionais e 9 específicos de IA). A coluna **Descrição** repete o texto original, sem reescrita.

**Item** aponta para o arquivo de `doc/` que cobre o requisito ([backlog.md](backlog.md) tem o índice). **Situação** é o estado do código que está no repositório hoje: *feito*, *parcial*, *não iniciado* ou *a medir* quando o requisito é um número que ninguém mediu. **Onde está no código** cita arquivo e função; travessão quer dizer que não existe código para esse requisito.

Nenhuma medição de latência, WER, acerto de extração ou de intenção foi feita até aqui, então todo requisito que exige número aparece como "a medir".

## Requisitos funcionais

| Código | Descrição | Item | Situação | Onde está no código |
| :-- | :-- | :-- | :-- | :-- |
| RF01 | Capturar o áudio do microfone pelo navegador em dispositivos móveis e transmiti-lo em streaming para o servidor. | ATD-01, PRO-01 | parcial — o navegador captura e manda os pedaços, o servidor só grava tudo num arquivo; nada consome esse áudio. Entrega em desktop, ver a última seção | `frontend/app.js`; `backend/main.py` → `websocket_audio` (rota `/ws/falar`) |
| RF02 | Transcrever a fala do cliente em tempo real, à medida que ele fala. | VOZ-01 | não iniciado — nenhuma linha de transcrição escrita | — |
| RF03 | Identificar o cliente no início da conversa por nome e CPF, consultando o banco de dados pelo CPF informado. | CLI-01 | parcial — o lado do banco está feito e testado, mas a identificação depende da transcrição, que não existe: hoje nada chama essa busca | `backend/repositorio.py` → `buscar_cliente_por_cpf`; `backend/seguranca.py` → `normalizar_cpf`, `cpf_valido`, `hashear_cpf` |
| RF04 | Cadastrar o cliente durante a própria conversa quando o CPF não for encontrado. | CLI-01 | parcial — a função de cadastro está pronta e valida nome, telefone e CPF; falta a conversa que decide quando chamá-la | `backend/repositorio.py` → `criar_cliente` |
| RF05 | Consultar o histórico do cliente, últimos pedidos e item mais pedido para subsidiar a recomendação. | PED-01 | parcial — as consultas estão prontas e o seed já tem 30 pedidos de histórico; ninguém as chama ainda | `backend/repositorio.py` → `historico_cliente`, `itens_mais_pedidos_do_cliente` |
| RF06 | Interpretar a intenção do cliente e manter o contexto do diálogo ao longo da sessão. | VOZ-01 | não iniciado — não há modelo de linguagem nem estado de sessão | — |
| RF07 | Consultar o cardápio para responder perguntas sobre produtos e preços. | PED-01 | parcial — a consulta ao cardápio está pronta e ignora acento e hífen da transcrição; a resposta falada não existe | `backend/repositorio.py` → `listar_cardapio`, `buscar_produtos`, `buscar_produto` |
| RF08 | Recomendar produtos com base no histórico quando o cliente estiver em dúvida. | PED-01 | parcial — os dados da recomendação existem; quem decide recomendar é o modelo, que não existe | `backend/repositorio.py` → `itens_mais_pedidos_do_cliente`, `itens_mais_pedidos_da_casa` |
| RF09 | Montar o pedido de forma estruturada ao longo da conversa, com itens, quantidades, endereço e forma de pagamento. | PED-01 | parcial — a gravação da estrutura completa está pronta e é transacional; montar ao longo da conversa depende de VOZ-01 | `backend/repositorio.py` → `salvar_pedido`, `interpretar_pagamento` |
| RF10 | Sintetizar a resposta em voz e devolvê-la ao cliente. | VOZ-01 | não iniciado — não há síntese de voz | — |
| RF11 | Encerrar a chamada, salvar o pedido no banco de dados e exibir o resumo. | PED-01, ATD-01 | parcial — o pedido de encerramento fecha o WebSocket e a gravação do pedido existe, mas nada liga uma coisa na outra: nenhum pedido é salvo ao fim da chamada | `backend/main.py` → `websocket_audio` (controle `encerrar_chamada`); `backend/repositorio.py` → `salvar_pedido` |

## Requisitos não funcionais

| Código | Descrição | Item | Situação | Onde está no código |
| :-- | :-- | :-- | :-- | :-- |
| RNF01 | Manter a latência entre o fim da fala e o início da resposta em áudio abaixo de uma meta a ser definida após teste real no hardware alvo. | MED-01 | a medir — a meta ainda não foi definida e não há pipeline para cronometrar | — |
| RNF02 | Executar inteiramente em infraestrutura local, sem custo de API de inteligência artificial. | INF-01 | parcial — tudo o que existe hoje roda local (Postgres em container, FastAPI e a tela na mesma máquina) e não há nenhuma chave de API no repositório; os modelos locais ainda não foram instalados | `docker-compose.yml`; `package.json` → script `dev`; `backend/requirements.txt`; `backend/config.py` → `URL_DO_BANCO` |
| RNF03 | Oferecer interface responsiva, com prioridade para dispositivos móveis. | ATD-01 | parcial — a tela existe e é a única interface do sistema, mas a entrega deste semestre é desktop, ver a última seção | `frontend/index.html`, `frontend/style.css` |
| RNF04 | Manter o funcionamento estável na presença de ruído ambiente. | VOZ-01, MED-01 | não iniciado — sem transcrição não há o que se comportar bem ou mal com ruído | — |
| RNF05 | Separar o código do motor (pipeline de voz, orquestração e banco) das regras de negócio (cardápio, produtos e lógica de recomendação), sem compromisso de generalização completa neste semestre. | DAD-01, PED-01 | parcial — o acesso ao banco já está isolado num módulo só, que é a única porta de entrada; o motor de voz não existe para ser separado | `backend/repositorio.py`; `backend/database.py`; `backend/models.py` |
| RNF06 | Armazenar o CPF com cuidado mínimo de segurança, sem expô-lo em texto puro. | CLI-01, DAD-01 | feito — o CPF só entra no banco como HMAC-SHA256 de 64 caracteres; coluna de texto puro não existe no esquema | `backend/seguranca.py` → `hashear_cpf`; `backend/config.py` → `SEGREDO_CPF`; coluna `cliente.cpf_hash` em `banco.sql` e `backend/models.py` |

## Requisitos específicos de IA

| Código | Descrição | Item | Situação | Onde está no código |
| :-- | :-- | :-- | :-- | :-- |
| RIA01 | Manter a taxa de erro de palavra (WER) da transcrição em até 15% em áudio limpo e até 30% com ruído ambiente. | VOZ-01, MED-01 | a medir — não há transcrição nem corpus de teste | — |
| RIA02 | Exigir confirmação verbal dos dados críticos reconhecidos por voz (CPF, quantidades, endereço e forma de pagamento), com acerto mínimo de 95% após a confirmação. | CLI-01, PED-01, MED-01 | parcial — as validações que sustentam a confirmação existem (dígito verificador do CPF, quantidade quebrada e pagamento ambíguo param o fluxo em vez de chutar); a confirmação falada não existe e o acerto está a medir | `backend/seguranca.py` → `cpf_valido`; `backend/repositorio.py` → `interpretar_pagamento`, `salvar_pedido` |
| RIA03 | Extrair o pedido de forma estruturada com acerto de no mínimo 90% dos diálogos de teste, considerando itens e quantidades. | VOZ-01, MED-01 | a medir — a extração não existe e não há diálogos de teste escritos | — |
| RIA04 | Validar todo item extraído pelo modelo contra o cardápio do banco antes de incluí-lo no pedido, de modo que a ocorrência de produtos inexistentes seja nula. | PED-01 | parcial — a validação está pronta e é obrigatória: item fora do cardápio ou ambíguo levanta erro e nada vai para o banco; falta o modelo que vai alimentá-la | `backend/repositorio.py` → `salvar_pedido`, `buscar_produtos`; produto inativo de teste em `backend/seed.py` (Pizza de Escarola com Bacon) |
| RIA05 | Classificar corretamente a intenção do cliente em no mínimo 90% dos casos, entre pedir item, tirar dúvida, alterar, confirmar, cancelar e encerrar. | VOZ-01, MED-01 | a medir — não há classificação de intenção | — |
| RIA06 | Manter o contexto da sessão por no mínimo dez turnos, permitindo que o cliente se refira a itens já mencionados sem repeti-los. | VOZ-01 | não iniciado — não existe estado de sessão nem histórico de turnos | — |
| RIA07 | Medir o tempo de cada etapa do pipeline (transcrição, inferência e síntese), de modo que a soma respeite a meta de latência do RNF01. | MED-01 | não iniciado — nenhuma etapa é cronometrada no servidor, e as etapas ainda não existem | — |
| RIA08 | Produzir resposta sintetizada inteligível, com nota média mínima de 4 em escala de 1 a 5 avaliada pelo grupo, e fator de tempo real inferior a 1. | VOZ-01, MED-01 | a medir — não há síntese para avaliar | — |
| RIA09 | Solicitar a repetição da fala quando a confiança da transcrição ficar abaixo do limiar definido, em vez de assumir o conteúdo reconhecido. | VOZ-01 | não iniciado — o limiar ainda não foi definido e não há confiança de transcrição para comparar | — |

## Requisitos afetados pela decisão de escopo

O escopo entregue neste semestre é chamada simulada, em desktop, no navegador. Não há telefonia real nem entrega em celular. Dois requisitos do documento oficial falam em dispositivos móveis e ficam em conflito com isso:

| Código | O que o documento promete | O que vai ser entregue |
| :-- | :-- | :-- |
| RF01 | Capturar o áudio do microfone pelo navegador **em dispositivos móveis** e transmiti-lo em streaming. | Captura pelo navegador em desktop. A API de captura de microfone do navegador é a mesma no celular, mas o teste, o ajuste e a demonstração são em desktop. |
| RNF03 | Interface responsiva, **com prioridade para dispositivos móveis**. | Interface desenhada e testada para desktop. |

Isso precisa ser resolvido de uma das duas formas, e a escolha é do grupo com a professora: ajustar a redação dos dois requisitos no documento oficial, trocando "dispositivos móveis" por "navegador", ou manter o texto e justificar a redução de escopo na banca. Deixar como está, sem decidir, é a pior opção: a banca lê o documento oficial e cobra o que está escrito nele.
