"""Servidor local: protótipo HTTP de eco e atendimento de voz por WebSocket."""

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from turno_de_voz import atender_turno

app = FastAPI(title="Backend Pizzaria - Agente de Voz", version="0.1.0")
LIMITE_AUDIO_BYTES = 25 * 1024 * 1024


@app.get("/health")
async def health():
    """Confirma o servidor; não representa um teste dos modelos ou do banco."""
    return {"status": "ok", "mensagem": "servidor fastapi da pizzaria rodando!"}


@app.get("/teste")
async def pagina_teste():
    return FileResponse(Path(__file__).resolve().parent / "teste_ws.html")


@app.post("/api/v1/falar", summary="Teste de transporte: devolve o áudio enviado")
async def processar_audio(audio: UploadFile = File(...)):
    """Eco de áudio, sem IA. Não usa o nome enviado pelo cliente como caminho em disco."""
    try:
        dados = await audio.read(LIMITE_AUDIO_BYTES + 1)
        if len(dados) > LIMITE_AUDIO_BYTES:
            raise HTTPException(413, "Áudio excede o limite de 25 MiB.")
        if not dados:
            raise HTTPException(400, "Envie um arquivo de áudio não vazio.")
        return Response(dados, media_type=audio.content_type or "application/octet-stream")
    finally:
        await audio.close()


async def erro_de_protocolo(websocket, mensagem, fatal=False):
    await websocket.send_json({"tipo": "erro", "onde": "audio", "mensagem": mensagem, "fatal": fatal})


@app.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """Binário é áudio; texto é controle JSON. Cada conexão possui seu próprio contexto."""
    await websocket.accept()
    await websocket.send_json({"tipo": "pronto", "versao_protocolo": 1, "capacidades": {"registro_pedidos": False}})
    audio_da_chamada = bytearray()
    amostra_inicio = 0
    historico = []
    try:
        while True:
            mensagem = await websocket.receive()
            if mensagem["type"] == "websocket.disconnect":
                break
            pedaco = mensagem.get("bytes")
            if pedaco is not None:
                if len(audio_da_chamada) + len(pedaco) > LIMITE_AUDIO_BYTES:
                    await erro_de_protocolo(websocket, "Áudio da chamada excede 25 MiB. Inicie outra chamada.", True)
                    await websocket.close(code=1009)
                    break
                # O primeiro chunk contém o cabeçalho: conservar a chamada inteira.
                audio_da_chamada.extend(pedaco)
                continue
            try:
                controle = json.loads(mensagem.get("text", ""))
            except json.JSONDecodeError:
                await erro_de_protocolo(websocket, "Controle deve ser um objeto JSON com a chave tipo.")
                continue
            if not isinstance(controle, dict) or not isinstance(controle.get("tipo"), str):
                await erro_de_protocolo(websocket, "Controle deve ser um objeto JSON com a chave tipo.")
                continue
            tipo = controle["tipo"]
            if tipo == "iniciar_chamada":
                if controle.get("versao_protocolo", 1) != 1:
                    await erro_de_protocolo(websocket, "Versão do protocolo não suportada.", True)
                    await websocket.close(code=1002)
                    break
            elif tipo == "fim_da_fala":
                amostra_inicio = await atender_turno(
                    websocket, audio_da_chamada, amostra_inicio, controle.get("turno"), historico
                )
            elif tipo == "encerrar_chamada":
                await websocket.send_json({"tipo": "chamada_encerrada", "motivo": controle.get("motivo", "cliente_desligou")})
                await websocket.close()
                break
            elif tipo not in ("resposta_tocada", "timeout"):
                await erro_de_protocolo(websocket, "Tipo de controle desconhecido.")
    except WebSocketDisconnect:
        pass


# Último: a API e a documentação têm precedência sobre os arquivos estáticos.
PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=PASTA_FRONTEND, html=True), name="frontend")
