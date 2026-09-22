from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import os
import shutil

app = FastAPI(title="Backend Pizzaria - Agente de Voz", version="0.1.0")

# --- rota 1: health check (pra confirmar se a api ta de pe) ---
@app.get("/")
async def root():
    return {"status": "ok", "mensagem": "servidor fastapi da pizzaria rodando!"}

# --- ROTA EXTRA: Apenas para servir a nossa página html de teste ---
@app.get("/teste")
async def pagina_teste():
    """
    Servindo o html pelo servidor pra driblar o bloqueio de microfone do navegador.
    """
    return FileResponse("teste_ws.html")

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

# --- rota 3: websocket para streaming de audio (fase 3) ---
@app.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """
    endpoint de websocket fase 3. 
    recebe chunks de audio, junta tudo num arquivo so e guarda.
    """
    await websocket.accept()
    print("[websocket] cliente conectou no tubo de streaming!")
    
    # a gnt cria um arquivo e abre ele no modo "wb" (write bytes)
    # ou "ab" (append bytes). vamos de "wb" e manter ele aberto.
    caminho_audio = "audio_cliente_streaming.webm"
    
    try:
        # abrimos o arquivo uma vez so, pra ir enchendo ele de dados
        with open(caminho_audio, "wb") as arquivo:
            while True:
                # recebe o pedacinho (chunk) do front
                data = await websocket.receive_bytes()
                
                # escreve o pedacinho no final do arquivo
                arquivo.write(data)
                print(f"[websocket] recebi e guardei um chunk de {len(data)} bytes")
                
                # manda um textinho pro front so pra confirmar q chegou
                await websocket.send_text("chunk guardado no backend!")
                
    except WebSocketDisconnect:
        # quando o cara desligar a chamada no front (ou fechar a aba), cai aqui
        print(f"[websocket] cliente desconectou.")
        print(f"[websocket] audio completo salvo em: {caminho_audio}")
        
        # --- MOCK DA FASE 3 ---
        # aqui seria o momento exato q a gente chamaria:
        # texto_do_cliente = roveris_transcrever(caminho_audio)
        # ----------------------