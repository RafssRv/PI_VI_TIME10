from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import os
import shutil

app = FastAPI(title="Backend Pizzaria - Agente de Voz", version="0.1.0")

# --- rota 1: health check (pra confirmar se a api ta de pe) ---
@app.get("/")
async def root():
    return {"status": "ok", "mensagem": "servidor fastapi da pizzaria rodando!"}

# --- rota 2: mock pra processar o audio inteiro (fases 1 e 2) ---
@app.post("/api/v1/falar")
async def processar_audio(audio: UploadFile = File(...)):
    """
    endpoint http padrao (fase 2).
    recebe o arquivo de audio inteiro, salva temporariamente e devolve de volta.
    """
    try:
        print(f"[http] audio recebido do front: {audio.filename}")
        
        caminho_temporario = f"temp_{audio.filename}"
        with open(caminho_temporario, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
            
        print(f"[http] arquivo salvo no disco como: {caminho_temporario}")
        
        return FileResponse(
            path=caminho_temporario, 
            media_type=audio.content_type, 
            filename=f"resposta_da_ia_{audio.filename}"
        )
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"erro": str(e)})

# =====================================================================
# NOVIDADE DA FASE 3 ABAIXO
# =====================================================================

# --- rota 3: websocket para streaming de audio (fase 3) ---
@app.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """
    endpoint de websocket. aqui a gnt nao recebe um arquivo inteiro,
    mas sim 'pedacinhos' (chunks) do audio em tempo real enquanto a pessoa fala.
    """
    # primeiro a gente aceita a conexao que o frontend pediu
    await websocket.accept()
    print("[websocket] cliente conectou no tubo de streaming!")
    
    try:
        # esse while true deixa o tubo aberto rodando sem parar
        while True:
            # recebe um pedacinho de dado (em bytes) do front
            data = await websocket.receive_bytes()
            print(f"[websocket] recebi um chunk de audio de {len(data)} bytes")
            
            # mock da fase 3: a gente devolve o mesmo chunk pro front (efeito eco)
            # na vida real (fase 3 final), a gnt ia repassar esses bytes pro roveris (IA)
            await websocket.send_bytes(data)
            
    except WebSocketDisconnect:
        # se o cliente fechar a pagina ou a ligacao cair, cai aqui
        print("[websocket] cliente desconectou da ligacao.")