<div align="center">

# Atendente de pedidos por voz

**Ninguém deveria perder um pedido por falta de atendente.**<br>
O cliente fala e a IA ouve, entende, consulta e responde em voz, tudo local.

**Estado atual:** protótipo com banco, tela de chamada, transcrição, atendimento com LLM e síntese de voz conectados no código.<br>
Os testes textuais de integração ainda mostram erros de interpretação. **O atendimento não está aprovado para uso real.**

<img align="absmiddle" alt="ouvir: faster-whisper" src="https://img.shields.io/badge/ouvir-faster--whisper-E4572E?style=flat-square&labelColor=24292F">
→
<img align="absmiddle" alt="entender: Llama 3.2" src="https://img.shields.io/badge/entender-Llama_3.2-E4572E?style=flat-square&logo=ollama&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="consultar: PostgreSQL" src="https://img.shields.io/badge/consultar-PostgreSQL-E4572E?style=flat-square&logo=postgresql&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="responder: Piper" src="https://img.shields.io/badge/responder-Piper-E4572E?style=flat-square&labelColor=24292F">

<sub>Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas</sub>

[A ideia](#a-ideia) · [Estado do projeto](#estado-do-projeto) · [Como funciona](#como-funciona) · [Como rodar](#como-rodar) · [Testes](#testes) · [Documentação](#documentação) · [Equipe](#equipe)

</div>

## A ideia

Na hora do pico, o telefone da pizzaria toca e ninguém atende. Contratar gente só para o pico sai caro, e assistentes de voz comerciais cobram por minuto e levam a conversa do cliente para a nuvem.

Este projeto desenvolve **um atendente de voz dentro do próprio estabelecimento**. O cliente abre o navegador, fala, e o sistema processa cada turno: transcreve o áudio, identifica o cliente, consulta o cardápio, monta o pedido e responde em voz. A inferência e o banco são locais, sem cobrança de API de IA.

O escopo do semestre é uma chamada simulada no navegador de desktop, sem telefonia real e sem validação para celular.

## Estado do projeto

| Componente | Situação |
| :-- | :-- |
| Banco e dados de demonstração | PostgreSQL com produtos, clientes, pedidos e script de carga. |
| Identificação e cadastro | Fluxo em código para consultar CPF, cadastrar e confirmar dados do cliente. |
| Tela e transporte | Interface de chamada e WebSocket para áudio, estados, transcrições e respostas. |
| Transcrição e voz | Serviços de faster-whisper e Piper chamados pelo processamento de cada turno. |
| Atendimento com LLM | Ollama recebe o prompt, o cardápio, o estado do pedido e o histórico da conversa. |
| Controle do pedido | Código valida itens, calcula valores, apresenta resumo e exige confirmação antes de gravar. |
| Validação funcional | Há testes automatizados e ensaios textuais com Ollama e PostgreSQL; ainda existem falhas. |

As pendências incluem interpretação incorreta de quantidades, perda ou mistura de observações e tratamento de transcrições ruins. Uma resposta bem formatada do modelo pode conter um pedido errado, mesmo quando o cálculo do subtotal está correto. Os testes de código usam respostas controladas e não comprovam que o modelo entendeu a fala.

Os ensaios de prompt documentados não validam o fluxo completo de microfone, navegador e reprodução de voz. Também falta comprovação de execução manual humana dos roteiros no Ollama: os registros existentes foram produzidos por scripts e pelo agente no chat de terminal.

## Como funciona

O navegador envia áudio pelo WebSocket. Ao terminar uma fala, o servidor converte o áudio, transcreve com Whisper e encaminha o texto para `Atendimento`. Essa classe conduz o cadastro e o pedido; o LLM auxilia na interpretação. O código consulta e grava no banco, gera o resumo e só anuncia registro após a gravação bem-sucedida. A resposta vira áudio pelo Piper e volta ao navegador.

```mermaid
flowchart LR
    nav(["Navegador<br/>do cliente"])
    subgraph srv["Máquina local · FastAPI + WebSocket"]
        stt["faster-whisper<br/>fala → texto"]
        atendimento["Atendimento<br/>fluxo e validações"]
        llm["Llama 3.2<br/>intenção + contexto"]
        controle["ControlePedido<br/>itens, valores e confirmação"]
        repo["Repositório<br/>consultas e gravação"]
        tts["Piper<br/>texto → fala"]
        db[("PostgreSQL")]
    end
    nav -- "áudio via WebSocket" --> stt --> atendimento
    atendimento <--> llm
    atendimento --> controle
    atendimento --> repo --> db
    atendimento --> tts -- "áudio" --> nav
```

O fluxo de voz usa `/ws/falar`. A rota HTTP `/api/v1/falar` continua sendo um teste de recebimento e devolução de arquivo; ela não executa o atendimento completo.

## Como rodar

Pré-requisitos: Git, Docker Desktop com Docker Compose, Node.js/npm, Python e Ollama instalados. Mantenha o Docker Desktop e o serviço do Ollama em execução; o backend acessa o Ollama em `http://127.0.0.1:11434`.

No PowerShell, usando um ambiente virtual:

```powershell
git clone https://github.com/RafssRv/PI_VI_TIME10.git
cd PI_VI_TIME10
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm run deps     # dependências Python do backend
ollama pull llama3.2:3b
npm run banco    # sobe o PostgreSQL no Docker
npm run seed     # popula cardápio, 6 clientes e 30 pedidos de histórico
npm run dev      # sobe o banco e o servidor na porta 3000
```

A tela fica em [localhost:3000](http://localhost:3000). Permita o uso do microfone no navegador. O endpoint [health](http://localhost:3000/health) verifica se o servidor responde; ele não testa o banco ou os modelos.

O Whisper usa o modelo `base` em CPU com `int8`; o primeiro carregamento pode precisar baixar o modelo. O Piper usa os arquivos de voz `pt_BR-cadu-medium` em `backend/agente/models/piper/`, incluídos no repositório. Os downloads iniciais de dependências e modelos exigem internet.

As configurações são lidas das variáveis de ambiente em [backend/config.py](backend/config.py):

| Variável | Uso |
| :-- | :-- |
| `DATABASE_URL` | Conexão SQLAlchemy. Padrão local: `postgresql+psycopg://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria`. |
| `AMBIENTE` | Padrão `dev`, que habilita a página de diagnóstico `/teste`. Fora desse ambiente, `/teste` fica indisponível e é obrigatório definir `CPF_HMAC_SECRET`. |
| `CPF_HMAC_SECRET` | Segredo para gerar o hash do CPF. Em desenvolvimento há um valor padrão; mantenha o mesmo valor ao carregar os dados e executar o servidor. Alterá-lo impede localizar os CPFs já cadastrados. |

## Testes

Com o ambiente virtual ativo e o PostgreSQL disponível:

```powershell
npm run teste
npm run teste:frontend
python scripts/validar_evidencias.py
```

A suíte direciona as operações para `pizzaria_teste` e recria o esquema desse banco. Não use esse nome para armazenar dados que deseja preservar. Os testes de atendimento substituem as respostas do Ollama; não exigem o modelo nem exercitam o áudio real.

Para conferir apenas o controle de pedido e a integridade das evidências, sem PostgreSQL:

```powershell
python -m pytest tests/test_controle_pedido.py tests/test_evidencias.py -q
```

O verificador de evidências confere referências, hashes e registros. Sua aprovação não significa aprovação funcional do atendente. Para repetir uma rodada textual com Ollama, use `python scripts/revalidar_prompt.py arquivo.json rodada saida.json`, informando uma evidência existente, o identificador da rodada e um arquivo de saída novo.

## Documentação

- [System prompt do atendente](backend/agente/prompt_sistema.txt).
- [Dados de evidência utilizados pelos testes e pelo verificador](doc/evidencias/).

## Equipe

Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | 24007131 |
