<div align="center">

# Atendente de pedidos por voz

**Ninguém deveria perder um pedido por falta de atente.**<br>
O cliente fala e a IA ouve, entende, consulta e responde em voz, tudo local.

**Estado hoje:** banco, tela de chamada e transporte de áudio prontos; transcrição, modelo de linguagem e síntese **não iniciados**.<br>
O estado item a item está em [doc/backlog.md](doc/backlog.md) — este README descreve o alvo, não o que já roda.

<img align="absmiddle" alt="ouvir: faster-whisper" src="https://img.shields.io/badge/ouvir-faster--whisper-E4572E?style=flat-square&labelColor=24292F">
→
<img align="absmiddle" alt="entender: Llama 3.2" src="https://img.shields.io/badge/entender-Llama_3.2-E4572E?style=flat-square&logo=ollama&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="consultar: PostgreSQL" src="https://img.shields.io/badge/consultar-PostgreSQL-E4572E?style=flat-square&logo=postgresql&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="responder: Piper" src="https://img.shields.io/badge/responder-Piper-E4572E?style=flat-square&labelColor=24292F">

<sub>Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas</sub>

[A ideia](#a-ideia) · [Como vai funcionar](#como-vai-funcionar) · [Como rodar](#como-rodar) · [Documentação](#documentação) · [Equipe](#equipe)

</div>

## A ideia

Na hora do pico, o telefone da pizzaria toca e ninguém atende. Contratar gente só para o pico sai caro, e assistentes de voz comerciais cobram por minuto e levam a conversa do cliente para a nuvem.

Este projeto coloca **um atendente de voz dentro do próprio estabelecimento**. A proposta: o cliente abre o navegador, faz o pedido falando, e o sistema transcreve em tempo real, entende a intenção, consulta cardápio e histórico, monta o pedido e responde em voz. Modelos abertos, sem custo de API e sem dados indo para terceiros.

Do que está descrito acima, o que existe hoje é a captura de áudio no navegador, o transporte pelo WebSocket e o banco de dados. Transcrição, modelo de linguagem, síntese e orquestração não têm nenhuma linha escrita — ver [doc/backlog.md](doc/backlog.md). O escopo deste semestre é chamada simulada, em desktop, sem telefonia real e sem celular.

Exemplo-alvo da conversa (**ainda não roda**):

```text
cliente    › Oi, queria pedir uma pizza.
atendente  › Claro! Qual é o seu nome e CPF?
cliente    › João, [diz o CPF].
atendente  › Achei seu cadastro, João. O que vai ser hoje?
cliente    › Hmm… não sei. O que você sugere?
atendente  › A sua mais pedida é a margherita. Vai uma grande?
cliente    › Pode ser. Entrega na Rua das Palmeiras, 120, e pago no Pix.
atendente  › Fechado: 1 margherita grande, Rua das Palmeiras, 120, no Pix. Pedido registrado!
```

## Como vai funcionar

Arquitetura pretendida. Hoje só existe o caminho `navegador → WebSocket → arquivo em disco`: faster-whisper, Llama 3.2 e Piper não foram instalados nem escritos, e o servidor não devolve nenhuma mensagem do protocolo.

```mermaid
flowchart LR
    nav(["Navegador<br/>do cliente"])
    subgraph srv["Máquina local · FastAPI + WebSocket"]
        stt["faster-whisper<br/>fala → texto"]
        llm["Llama 3.2<br/>intenção + contexto"]
        tts["Piper<br/>texto → fala"]
        db[("PostgreSQL")]
    end
    nav -- "áudio" --> stt --> llm --> tts -- "áudio" --> nav
    llm <--> db
```

## Como rodar

Pré-requisitos: Git, Docker Desktop, Node.js e Python. Com tudo instalado:

```bash
git clone https://github.com/RafssRv/PI_VI_TIME10.git
cd PI_VI_TIME10
npm run deps     # dependências Python do backend
npm run banco    # sobe o Postgres no Docker (precisa do Docker Desktop aberto)
npm run seed     # popula cardápio, 6 clientes e 30 pedidos de histórico
npm run dev      # sobe o banco e o servidor na porta 3000
```

A tela fica na raiz: <http://localhost:3000>. Conexão com o banco: `postgresql://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria`

Roteiro completo, com a instalação passo a passo, o que cada script faz e os erros mais comuns: [doc/INF-01-ambiente-local.md](doc/INF-01-ambiente-local.md).

## Documentação

- Estado de cada item do projeto: [doc/backlog.md](doc/backlog.md)
- Os 26 requisitos e onde cada um está no código: [doc/requisitos.md](doc/requisitos.md)
- Roadmap: [ordem sugerida de ataque](doc/backlog.md#ordem-sugerida-de-ataque), no backlog
- Um arquivo por item, em [doc/](doc): ambiente (INF-01), modelo de dados (DAD-01), identificação do cliente (CLI-01), pedido e cardápio (PED-01), pipeline de voz (VOZ-01), protocolo WebSocket (PRO-01), tela de chamada (ATD-01) e medição (MED-01)

## Equipe

Projeto Integrador VI Time 10 · Engenharia de Software PUC-Campinas

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | |
