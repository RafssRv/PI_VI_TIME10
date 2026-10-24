# Logs do atendimento

O servidor registra metadados operacionais, sem copiar falas, respostas do
modelo, CPF, nome, telefone, endereço, nomes de arquivos enviados ou
parâmetros SQL. As falas e a comanda continuam disponíveis na interface
durante a chamada; esta política trata dos logs, não da exibição do pedido.

Cada `Atendimento` gera um UUID aleatório em `id_chamada`, compartilhado
pelos registros da conexão, do turno de voz e do roteiro. Esse identificador
não é derivado do cliente e muda a cada chamada. Uploads HTTP recebem um
identificador aleatório próprio (`requisicao`).

Exemplo de diagnóstico:

```text
chamada=9a37521365904ce68a043e3ece259e2f turno=3 etapa=piper categoria=sintese
```

- `WARNING`: falhas com etapa e categoria fixa, como `banco`, `validacao`,
  `modelo_invalido`, `dependencias`, `decodificacao`, `transcricao`,
  `fala_vazia`, `atendimento`, `sintese`, `arquivo` ou `inesperada`.
- `INFO`: conexão, conclusão de transcrição/atendimento e recebimento de upload.
- `DEBUG`: quantidade de bytes recebidos por bloco, sem conteúdo.

Os módulos usam `logging` da biblioteca padrão e respeitam os handlers e
níveis configurados pelo processo. Não configuram o logger raiz nem criam
arquivos de log. Avisos são emitidos no nível padrão `WARNING`; os registros
`INFO` e `DEBUG` dependem da configuração de logging da aplicação.

Não adicionar `str(erro)`, `repr(erro)`, `exc_info`, `logger.exception`,
objetos completos ou valores recebidos em mensagens de diagnóstico.
Exceções de banco podem carregar parâmetros SQL e detalhes do registro.
As respostas de erro HTTP e de voz usam mensagens fixas. Falhas inesperadas
no processamento WebSocket geram erro fatal genérico e fechamento `1011`,
quando a conexão ainda permite enviar.

Se a conexão cair durante uma etapa em thread, o trabalho não é cancelado:
ele pode estar gravando um pedido. Sua exceção é observada ao terminar, sem
imprimir o conteúdo, evitando o traceback automático de tarefa abandonada
do asyncio.

O processo do Piper tem stdout/stderr descartados, pois uma ferramenta pode
repetir o texto de entrada nesses canais. Falhas continuam sendo detectadas
pelo código de saída; detalhes textuais do processo não ficam disponíveis
no terminal. O fluxo legado em `backend/agente/main.py` retorna os textos,
mas não os imprime.

O painel de logs e o console do frontend recebem descrições fixas dos
eventos. Mensagens desconhecidas, campos inválidos e detalhes de erro não
são copiados para esses destinos. A tarja de erro continua exibindo o aviso
recebido, e o backend envia avisos sem detalhes internos.

## Escopo e verificação

Esta alteração não apaga logs anteriores nem arquivos de áudio, e não muda
a retenção de dados no banco. Logs dos serviços externos (PostgreSQL,
Ollama e infraestrutura) e configurações extras de bibliotecas precisam
de política própria. O seed continua mostrando exemplos sintéticos para
desenvolvimento; `scripts/diagnostico/teste_ia.py` continua sendo um diagnóstico manual com
resposta de exemplo. Esses scripts não executam no atendimento do servidor.

`python -m pytest tests/test_logs.py -q` verifica cadastro/pedido completos,
falhas com dados pessoais no texto e nos parâmetros SQL, upload, fechamento
de conexão, fluxo legado e saída de um processo simulado de síntese.
`npm run teste:frontend` verifica também console e painel de log com dados
pessoais em mensagens e campos inválidos. Os modelos e o microfone são
simulados; o fluxo de cadastro/pedido usa PostgreSQL de teste.
