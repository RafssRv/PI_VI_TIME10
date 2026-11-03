# Atendente de pedidos por voz

Projeto Integrador VI, Time 10 — Engenharia de Software, PUC-Campinas.

Atendimento de pizzaria pelo navegador: Whisper transcreve a fala, o backend controla o pedido com apoio do Ollama e o Piper gera a resposta em voz. O banco e os modelos rodam localmente. O escopo é desktop, sem telefonia real.

## Como rodar

Instale Python, Node.js/npm, Docker Desktop e Ollama. Com Docker e Ollama em execução, abra o PowerShell na pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm run deps
ollama pull llama3.2:3b
npm run banco
npm run seed
npm run dev
```

Abra [localhost:3000](http://localhost:3000) e permita o microfone. Execute `seed` na preparação inicial; os demais comandos npm estão em [package.json](package.json).

O Whisper baixa o modelo `base` no primeiro uso. A voz do Piper fica em `backend/agente/models/piper/`.

## Configuração

Variáveis de ambiente lidas por [backend/config.py](backend/config.py):

| Variável | Uso |
| :-- | :-- |
| `DATABASE_URL` | Padrão: `postgresql+psycopg://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria`. |
| `AMBIENTE` | Padrão `dev`, que habilita a página de diagnóstico `/teste`. |
| `CPF_HMAC_SECRET` | Obrigatório fora de `dev`. Mantenha o mesmo segredo na carga dos dados e no servidor. |

## Estrutura

- `backend/`: API, atendimento, banco e regras de pedido.
- `backend/agente/`: prompt, interpretação de pedidos, serviços de voz e modelos.
- `frontend/`: interface da chamada, estilos e recursos visuais.
- `database/banco.sql`: esquema aplicado pelo Docker e pelos testes.
- `scripts/diagnostico/`: página de diagnóstico do WebSocket, disponível em `/teste` durante o desenvolvimento.
- `tests/`: testes Python; `tests/frontend/` reúne os testes JavaScript.

O prompt utilizado pelo atendimento está em [backend/agente/prompt_sistema.txt](backend/agente/prompt_sistema.txt).

## Testes

Com o ambiente virtual ativo e o PostgreSQL em execução:

```powershell
npm run teste
npm run teste:frontend
```

Os testes Python recriam o esquema de `pizzaria_teste`, separado do banco da aplicação. Não use esse banco para dados que deseja preservar. Os testes automatizados não substituem a validação com microfone e modelos reais.

## Equipe

| Integrante | RA |
| :-- | :-- |
| Anderson Lucas do Nascimento Gondim | 24787293 |
| Arthur Sebastian Guarniz de Castro | 24795528 |
| Felipe Nonato Leoneli | 24021973 |
| Filipe Ribeiro Simões | 24007657 |
| Rafael Roveri Pires | 24007131 |
