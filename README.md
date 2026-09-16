<div align="center">

# Atendente de pedidos por voz

**Ninguém deveria perder um pedido por falta de quem atenda.**<br>
O cliente fala pelo celular e a IA ouve, entende, consulta e responde em voz, tudo numa máquina local.

<img align="absmiddle" alt="ouvir: faster-whisper" src="https://img.shields.io/badge/ouvir-faster--whisper-E4572E?style=flat-square&labelColor=24292F">
→
<img align="absmiddle" alt="entender: Llama 3.2" src="https://img.shields.io/badge/entender-Llama_3.2-E4572E?style=flat-square&logo=ollama&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="consultar: PostgreSQL" src="https://img.shields.io/badge/consultar-PostgreSQL-E4572E?style=flat-square&logo=postgresql&logoColor=white&labelColor=24292F">
→
<img align="absmiddle" alt="responder: Piper" src="https://img.shields.io/badge/responder-Piper-E4572E?style=flat-square&labelColor=24292F">

<sub>Projeto Integrador VI · Engenharia de Software · PUC-Campinas · Time 10</sub>

[A ideia](#a-ideia) · [Como funciona](#como-funciona) · [Como rodar](#como-rodar) · [Documentação](#documentação) · [Equipe](#equipe)

</div>

## A ideia

Na hora do pico, o telefone da pizzaria toca e ninguém atende. Contratar gente só para o pico sai caro, e assistentes de voz comerciais cobram por minuto e levam a conversa do cliente para a nuvem.

Este projeto coloca **um atendente de voz dentro do próprio estabelecimento**. O cliente abre o navegador do celular e faz o pedido falando; o sistema transcreve em tempo real, entende a intenção, consulta cardápio e histórico, monta o pedido e responde em voz. Modelos abertos, sem custo de API e sem dados indo para terceiros.

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

## Como funciona

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

```bash
git clone https://github.com/RafssRv/PI_VI_TIME10.git
cd PI_VI_TIME10
docker compose up -d
```

Conexão: `postgresql://pizzaria:pizzaria123@localhost:5432/pizzaria`

## Documentação

Documentação: 
Roadmap: 

## Equipe

Time 10 · Projeto Integrador VI · Engenharia de Software PUC-Campinas · 2º semestre de 2026

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | |