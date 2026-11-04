"""Monta a API e serve o frontend; o fluxo de voz fica em rotas.voz."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import AMBIENTE
from rotas.voz import router as rotas_de_voz
from rotas.admin import router as rotas_do_admin

RAIZ = Path(__file__).resolve().parent.parent
app = FastAPI(title="Backend Pizzaria - Agente de Voz", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "mensagem": "servidor fastapi da pizzaria rodando!"}


if AMBIENTE == "dev":
    @app.get("/teste", include_in_schema=False)
    async def pagina_teste():
        return FileResponse(RAIZ / "scripts" / "diagnostico" / "teste_ws.html")


app.include_router(rotas_de_voz)
# o painel ainda nao tem login: so existe em desenvolvimento, igual a pagina /teste
if AMBIENTE == "dev":
    app.include_router(rotas_do_admin)
# O mount fica por último para não capturar as rotas HTTP/WebSocket da API.
app.mount("/", StaticFiles(directory=RAIZ / "frontend", html=True), name="frontend")
