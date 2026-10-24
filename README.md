<div align="center">

# Atendente de pedidos por voz

**Ninguém deveria perder um pedido por falta de atendente.**<br>
O cliente fala e a IA ouve, entende, consulta e responde em voz, tudo local.

**Estado atual:** protótipo com banco, interface de chamada, transcrição, atendimento com LLM e síntese de voz integrados no código.<br>
Os testes automatizados não substituem a validação do atendimento completo com microfone e modelos reais.

<img align="absmiddle" alt="ouvir: faster-whisper" src="https://img.shields.io/badge/ouvir-faster--whisper-E4572E?style=flat-square&labelColor=24292F">
→
<img align="absmiddle" alt="entender: Llama 3.2" src="https://img.shields.io/badge/entender-Llama_3.2-E4572E?style=flat-square&logo=ollama&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="consultar: PostgreSQL" src="https://img.shields.io/badge/consultar-PostgreSQL-E4572E?style=flat-square&logo=postgresql&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="responder: Piper" src="https://img.shields.io/badge/responder-Piper-E4572E?style=flat-square&labelColor=24292F">

<sub>Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas</sub>

[A ideia](#a-ideia) · [Como funciona](#como-funciona) · [Como rodar](#como-rodar) · [Testes](#testes) · [Arquivos utilizados](#arquivos-utilizados) · [Equipe](#equipe)

</div>

## A ideia

Na hora do pico, o telefone da pizzaria toca e ninguém atende. Contratar gente só para o pico sai caro, e assistentes de voz comerciais cobram por minuto e levam a conversa do cliente para a nuvem.

Este projeto coloca **um atendente de voz dentro do próprio estabelecimento**. A proposta: o cliente abre o navegador, faz o pedido falando, e o sistema transcreve em tempo real, entende a intenção, consulta cardápio e histórico, monta o pedido e responde em voz. Modelos abertos, sem custo de API e sem dados indo para terceiros.

O escopo deste semestre é uma chamada simulada no navegador de desktop, sem telefonia real e sem validação para celular.

## Como funciona

O navegador envia áudio por `/ws/falar`. O servidor transcreve com Whisper, conduz o cadastro e o pedido por meio de `Atendimento` e gera a resposta em voz com Piper. O LLM auxilia na interpretação; o código consulta e grava no banco.

```mermaid
flowchart LR
    nav(["Navegador<br/>do cliente"])
    subgraph srv["Máquina local · FastAPI + WebSocket"]
        stt["faster-whisper<br/>fala → texto"]
        atendimento["Atendimento<br/>fluxo e validações"]
        llm["Llama 3.2<br/>intenção + contexto"]
        tts["Piper<br/>texto → fala"]
        db[("PostgreSQL")]
    end
    nav -- "áudio" --> stt --> atendimento
    atendimento <--> llm
    atendimento --> db
    atendimento --> tts -- "áudio" --> nav
```

## Como rodar

Pré-requisitos: Git, Docker Desktop com Docker Compose, Node.js/npm, Python e Ollama. Mantenha Docker Desktop e Ollama em execução. No PowerShell:

```powershell
git clone https://github.com/RafssRv/PI_VI_TIME10.git
cd PI_VI_TIME10
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm run deps     # dependências Python do backend
ollama pull llama3.2:3b
npm run banco    # sobe o Postgres no Docker (precisa do Docker Desktop aberto)
npm run seed     # popula cardápio, 6 clientes e 30 pedidos de histórico
npm run dev      # sobe o banco e o servidor na porta 3000
```

A tela fica na raiz: <http://localhost:3000>. Conexão com o banco: `postgresql://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria`

Permita o uso do microfone no navegador. As configurações `DATABASE_URL`, `AMBIENTE` e `CPF_HMAC_SECRET` estão em [backend/config.py](backend/config.py). Fora de `AMBIENTE=dev`, defina `CPF_HMAC_SECRET`; mantenha o mesmo segredo entre a carga dos dados e a execução do servidor.

## Testes

Com o ambiente virtual ativo e o PostgreSQL disponível:

```powershell
npm run teste
python scripts/validar_evidencias.py
```

A suíte recria o esquema do banco `pizzaria_teste`; não use esse banco para dados que deseja preservar. O verificador de evidências confere a integridade dos registros, sem aprovar o comportamento do modelo.

## Arquivos utilizados

- [Prompt do atendente](backend/agente/prompt_sistema.txt): instruções carregadas pelo atendimento.
- [Evidências em JSON](doc/evidencias/): dados utilizados pelos testes e pelo verificador de evidências.

## Equipe

Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | |
