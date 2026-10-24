# Melhorias do backend e frontend por etapas

Escopo aprovado: corrigir os itens 1 (comanda), 3 (validação do WebSocket)
e 6 (dados pessoais nos logs) da revisão e executar a reorganização proposta.
Manter FastAPI, PostgreSQL e JavaScript puro. Uma etapa por resposta;
o usuário revisa e executa cada commit antes da próxima etapa.

## Sequência e verificações

- [x] 1. Integrar atendimento e comanda: enviar `pedido` e `pedido_salvo`,
  preservar o resumo após salvar e não confirmar gravações que falharam.
  Testar o atendimento e o turno de voz com PostgreSQL de teste e serviços
  de áudio/LLM simulados. Commit: `fix(atendimento): sincroniza pedido e comanda`.
- [x] 2. Validar o protocolo em `backend/protocolo.py`: rejeitar mensagens
  inválidas, limitar bytes/duração e documentar o contrato em
  `doc/protocolo-websocket.md`. Testar entradas inválidas e limites.
- [x] 3. Remover dados pessoais dos logs: registrar etapa, identificador e
  categoria de falha sem transcrição ou parâmetros pessoais. Testar CPF,
  telefone/endereço e exceções que contenham esses dados.
- [x] 4. Reorganizar backend: extrair `backend/rotas/voz.py` e
  `backend/interpretacao.py`; mover diagnósticos para `scripts/diagnostico/`;
  servir diagnóstico somente em desenvolvimento. Atualizar referências,
  executar a suíte e verificar rotas/imports.
- [ ] 5. Reorganizar frontend: módulos em `frontend/js/` para conexão,
  áudio, comanda e coordenação; interface explícita para efeitos visuais.
  Verificar carregamento, mensagens, controles e comportamento da comanda.
- [ ] 6. Introduzir migrações incrementais em `backend/migrations/`, com
  comando e documentação; validar instalação nova, banco existente e
  reaplicação sem perda de dados.

## Decisões de integração

- Preservar `Atendimento.responder()` para os consumidores existentes.
  O turno de voz recebe texto e eventos estruturados por uma nova operação.
- Dinheiro no protocolo usa strings com duas casas decimais.
- O evento `pedido` identifica se é rascunho (`pedido_id: null`) ou salvo.
  Começar outro pedido não pode herdar o identificador da venda anterior.
- Emitir a confirmação persistida antes da síntese de voz, para que uma
  falha do Piper não esconda uma gravação já concluída.
- Não alterar nem incluir nos commits mudanças preexistentes do usuário.

## Registro de execução

Etapa 1 implementada. Base: `17b0475`, branch `develop`.
O `README.md` já estava staged antes da implementação e será preservado.

Validação: 236 testes Python passaram usando o PostgreSQL local na porta
55432 e o banco isolado `pizzaria_teste`; 2 testes Node passaram com
`npm run teste:frontend`. Sintaxe JavaScript e `git diff --check` passaram.
Os testes novos falharam antes das correções. Áudio e LLM foram simulados;
não houve teste com microfone ou modelos reais nesta etapa.

O usuário executará o commit antes da etapa 2. Não houve staging nem commit
automático dos arquivos desta etapa.

### Etapa 2 — validação do WebSocket

Etapa 1 commitada pelo usuário em `d2031c4`. Trabalho seguinte na branch
`features/melhorias-backend-frontend`; o README staged continua separado.

Implementados contrato de entrada, abertura única, validação de turnos e
limites de 4 KiB por controle, 1 MiB por bloco, 20 MiB de áudio acumulado e
15 minutos de recepção. O relógio não é reiniciado por frames. Um turno já
em processamento conclui antes do encerramento por prazo; não foi criado
timeout de execução dos modelos nesta etapa.

Frontend e diagnóstico enviam a abertura antes do áudio. O diagnóstico
escolhe formato explícito e libera o microfone ao encerrar ou falhar.
Contrato, códigos de fechamento e limitações estão em `protocolo-websocket.md`.

Validação: 286 testes Python e 5 testes Node passaram. Regressões de entradas
inválidas, limites, ordem de abertura e formato do diagnóstico falharam antes
das respectivas correções. Testes usam frames ASGI reais do Starlette e
simulação do pipeline/microfone; não houve chamada com modelos reais.

Commit proposto: `fix(websocket): valida protocolo e limita audio por chamada`.
O usuário fará esse commit antes da etapa 3 (dados pessoais nos logs).

### Etapa 3 — dados pessoais nos logs

Etapa 2 commitada pelo usuário em `59a492f`. O README staged continua
separado e não foi modificado por esta etapa.

Transcrições, respostas, nomes de arquivos recebidos e exceções brutas
foram removidos dos logs. Cada atendimento recebe um identificador
aleatório; os registros indicam etapa e categoria fixa da falha. Erros
HTTP/WebSocket não devolvem detalhes internos. Uma falha inesperada na
chamada retorna erro fatal genérico e fecha com `1011`.

O fluxo legado deixa de imprimir falas; o subprocesso do Piper não herda
stdout/stderr. O frontend deixa de copiar mensagens, campos inválidos e
exceções para o painel de logs/console. Conversa, comanda e avisos continuam
disponíveis na interface. A política e os limites estão documentados em
`logs-e-privacidade.md`.

Falhas tardias de tarefas em thread são observadas após desconexão ou
cancelamento, sem traceback automático e sem interromper uma gravação.

Validação: 308 testes Python e 15 testes Node passaram; sintaxe JavaScript
e `git diff --check` passaram. Os testes de regressão reproduziram os
vazamentos antes das correções. PostgreSQL de teste real; voz, modelo e
microfone simulados. Sem nova dependência.

Commit proposto: `fix(privacidade): remove dados pessoais dos logs`.
O usuário fará esse commit antes da etapa 4 (reorganização do backend).

### Etapa 4 — reorganização do backend

Etapa 3 commitada pelo usuário em `ddbc81d`. README staged preservado.

`main.py` monta a aplicação; upload e WebSocket ficam em `rotas/voz.py`.
`interpretacao.py` reúne parsing de texto e validação da resposta do modelo,
sem dependência de banco ou serviços de IA. O fluxo do atendimento e as
validações de negócio permanecem nas classes e funções existentes.

Decisão: mover também a normalização compartilhada do repositório para
`interpretacao.py`, mantendo seu import no repositório. Isso evita uma
dependência de banco no módulo de interpretação e mantém o mesmo algoritmo.

`teste_ws.html` e `teste_ia.py` foram movidos para `scripts/diagnostico/`.
`/teste` é registrado apenas em desenvolvimento; fora de `AMBIENTE=dev`,
retorna 404. Os scripts de evidências existentes permanecem em `scripts/`.
A estrutura e os comandos estão em `estrutura-backend.md`.

Validação: 315 testes Python e 15 testes Node passaram. Os testes de rotas
reproduziram o acesso indevido ao diagnóstico fora de desenvolvimento antes
da correção. O WebSocket agora é testado pela aplicação ASGI completa.
PostgreSQL de teste real; áudio/LLM simulados. Sem nova dependência.

Commit proposto: `refactor(backend): separa rotas interpretacao e diagnosticos`.
O usuário fará esse commit antes da etapa 5 (reorganização do frontend).
