# Backlog

A pasta `doc/` guarda um arquivo por item do projeto: o que o item resolve, por onde se entra, o que ele lê e grava no banco, as regras que o código obriga e o que ficou de fora. `requisitos.md` é a ponte entre os 26 requisitos do documento oficial e esses itens.

Status vale para o código que está no repositório hoje, não para o que está planejado: **pronto** é código escrito e rodado contra o Postgres, **parcial** é uma parte entregue e outra dependendo de algo que não existe, **não iniciado** é nenhuma linha escrita. Onde não existe medição, a palavra é "a medir".

| ID | Item | Status | Arquivo |
| :-- | :-- | :-- | :-- |
| backlog.md | Índice do backlog | pronto | este arquivo |
| requisitos.md | Os 26 requisitos e onde cada um está | pronto | [requisitos.md](requisitos.md) |
| INF-01 | Ambiente local | pronto | [INF-01-ambiente-local.md](INF-01-ambiente-local.md) |
| DAD-01 | Modelo de dados | pronto | [DAD-01-modelo-de-dados.md](DAD-01-modelo-de-dados.md) |
| CLI-01 | Identificação do cliente | parcial | [CLI-01-identificacao-do-cliente.md](CLI-01-identificacao-do-cliente.md) |
| PED-01 | Pedido e cardápio | parcial | [PED-01-pedido-e-cardapio.md](PED-01-pedido-e-cardapio.md) |
| PRO-01 | Protocolo WebSocket | parcial | [PRO-01-protocolo-websocket.md](PRO-01-protocolo-websocket.md) |
| ATD-01 | Tela de chamada | parcial | [ATD-01-tela-de-chamada.md](ATD-01-tela-de-chamada.md) |
| VOZ-01 | Pipeline de voz | não iniciado | [VOZ-01-pipeline-de-voz.md](VOZ-01-pipeline-de-voz.md) |
| MED-01 | Medição e validação | não iniciado | [MED-01-medicao-e-validacao.md](MED-01-medicao-e-validacao.md) |

O que está pronto e testado contra o Postgres é o esquema (`banco.sql`), os models (`backend/models.py`), o hash de CPF (`backend/seguranca.py`), o repositório (`backend/repositorio.py`) e o seed com cardápio, 6 clientes e 30 pedidos de histórico (`backend/seed.py`). Transcrição, modelo de linguagem, síntese e orquestração não têm nenhuma linha escrita.

## Ordem sugerida de ataque

Itens com trabalho pendente, na ordem em que fazem sentido ser construídos.

1. **VOZ-01 — pipeline de voz.** Vem primeiro porque tudo depende dele: sem transcrição não há intenção, sem intenção não há pedido montado, e sem síntese não há resposta. Seis requisitos funcionais e sete de IA estão travados aqui.
2. **PRO-01 — protocolo WebSocket.** Assim que o pipeline tiver a primeira transcrição, é o protocolo que leva estado, transcrição, áudio e pedido até a tela; hoje o servidor recebe os frames de texto mas não tem o que responder.
3. **ATD-01 — tela de chamada.** A tela só sai do modo mudo quando o servidor se apresenta, então ela fecha o ciclo depois que PRO-01 estiver entregando mensagens de verdade.
4. **CLI-01 — identificação do cliente.** O lado do banco já está pronto; falta o trecho da conversa que colhe nome e CPF, confirma com o cliente e decide entre buscar e cadastrar.
5. **PED-01 — pedido e cardápio.** Também só tem a metade do banco pronta; falta o modelo montar o pedido turno a turno e chamar `salvar_pedido` no fim da chamada.
6. **MED-01 — medição e validação.** Por último porque só se mede o que existe: é ele que produz os números de latência, WER, extração e intenção que a banca vai cobrar.

## Riscos

1. **O pipeline inteiro ainda não existe.** Transcrição, modelo de linguagem, síntese, streaming real e orquestração estão em zero. É a maior parte do trabalho e a que mais requisitos carrega (RF01, RF02, RF06, RF10 e quase todos os RIA).
2. **Nenhuma medição foi feita e nove requisitos exigem número.** RNF01, RIA01, RIA02, RIA03, RIA05, RIA06, RIA07, RIA08 e RIA09 pedem meta, percentual ou limiar. Nenhum foi medido, e a meta do RNF01 nem foi definida, porque depende de teste no hardware alvo.
3. **O documento oficial promete celular e a entrega é desktop.** RF01 e RNF03 falam em dispositivos móveis; o escopo deste semestre é chamada simulada em desktop no navegador. Ou o documento é ajustado, ou a decisão é justificada na banca.
4. **O áudio em streaming é a parte mais difícil e ninguém começou.** Fatiar o áudio, decidir quando a fala terminou, transcrever enquanto o cliente ainda fala e devolver voz sem deixar o silêncio longo é o ponto onde o projeto pode travar.
5. **O segredo do HMAC do CPF não pode mudar depois do primeiro cadastro.** `CPF_HMAC_SECRET` entra no hash gravado em `cliente.cpf_hash`; trocar o segredo invalida todos os CPFs já gravados e ninguém mais é encontrado pela busca.
