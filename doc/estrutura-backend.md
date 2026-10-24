# Organização do backend

```text
backend/
  main.py                  # monta a aplicação, health check e arquivos estáticos
  rotas/
    __init__.py
    voz.py                 # upload HTTP e conexão WebSocket
  protocolo.py             # valida controles e define limites da conexão
  turno_de_voz.py           # coordena transcrição, atendimento e síntese
  atendimento.py           # cadastro, conversa, comanda e confirmação do pedido
  interpretacao.py          # interpretação de texto e estrutura da resposta do modelo
  repositorio.py           # consultas e gravações com validação de negócio
  database.py              # engine e sessões SQLAlchemy
  models.py                # modelos do banco
  seguranca.py             # validação e hash de CPF
  config.py                # configuração por ambiente
  seed.py                  # dados sintéticos de desenvolvimento
  agente/
    controle_pedido.py      # regras de edição e confirmação do carrinho
    services/              # adaptadores de áudio, Whisper, Ollama e Piper
    prompt_sistema.txt
scripts/
  diagnostico/
    teste_ws.html          # página manual de captura de áudio
    teste_ia.py             # chamada manual de exemplo ao Ollama
```

`main.py` registra o router de voz antes de montar o frontend. Os caminhos
públicos continuam sendo `/health`, `/api/v1/falar` e `/ws/falar`; a raiz
entrega a interface. A configuração de execução continua usando `main:app`.

`interpretacao.py` usa apenas a biblioteca padrão. Ele reúne extração de
dígitos, nome e endereço, confirmação explícita, auxiliares de trocas,
normalização de texto, schema do modelo e validação da estrutura JSON.
Não consulta o banco, carrega modelos ou decide se um pedido pode ser salvo.
O atendimento continua conferindo produtos, preços, quantidades e pagamento
antes da confirmação; o repositório usa a mesma normalização de texto.

## Execução

Na raiz do projeto, usando o Python com as dependências instaladas:

```powershell
rtk proxy python -m uvicorn main:app --app-dir backend --reload --port 3000
```

O comando existente `npm run dev` também continua funcionando. Os arquivos
estáticos e a página de diagnóstico são localizados a partir de `main.py`,
sem depender da pasta em que o servidor foi iniciado.

## Diagnóstico

Com `AMBIENTE=dev` (valor padrão local), `/teste` serve a página movida para
`scripts/diagnostico/teste_ws.html`. Fora de `dev`, `/teste` retorna `404`.
A pasta `scripts/` não é exposta pelo mount de arquivos estáticos. Reinicie
o servidor ao mudar `AMBIENTE`, pois a configuração é lida na inicialização.

O diagnóstico textual continua manual e requer o serviço Ollama:

```powershell
rtk proxy python scripts/diagnostico/teste_ia.py
```

`scripts/revalidar_prompt.py` e `scripts/validar_evidencias.py` permanecem
onde estavam: são ferramentas de validação de evidências, já separadas
do servidor. O fluxo legado `backend/agente/main.py` permanece disponível.

## Verificação

`tests/test_rotas.py` verifica os caminhos públicos e o bloqueio de `/teste`
em produção/homologação. `tests/test_websocket.py` passa pela aplicação ASGI
completa, incluindo o router. Os testes de atendimento, persistência e
privacidade continuam cobrindo o comportamento após a extração.

A organização dos módulos JavaScript será feita na próxima etapa. Esta
etapa não muda o schema do banco nem a política de arquivos de áudio.
