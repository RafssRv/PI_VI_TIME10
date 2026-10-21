from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import json
import os
import shutil
from pathlib import Path
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Backend Pizzaria - Agente de Voz", version="0.1.0")

# --- health check (pra confirmar se a api ta de pe) ---
@app.get("/health")
async def health():
    return {"status": "ok", "mensagem": "servidor fastapi da pizzaria rodando!"}

# --- ROTA EXTRA: Apenas para servir a nossa página html de teste ---
@app.get("/teste")
async def pagina_teste():
    """
    Servindo o html pelo servidor pra driblar o bloqueio de microfone do navegador.
    """
    return FileResponse(Path(__file__).resolve().parent / "teste_ws.html")

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
#
# protocolo combinado com a tela (frontend/app.js):
#   frame binario = pedaco de audio do cliente
#   frame de texto = json de controle, sempre com a chave "tipo"
#
# tela -> servidor:  iniciar_chamada (traz o formato do audio), fim_da_fala,
#                    resposta_tocada, encerrar_chamada
# servidor -> tela:  pronto, estado, transcricao, audio_resposta, pedido,
#                    pedido_salvo, erro, chamada_encerrada
#
# a tela nasce muda, so mandando binario, e so passa a mandar json depois que a gente
# se apresentar com {"tipo": "pronto"}. enquanto o pipeline de voz nao existir a gente
# NAO manda o pronto de proposito: se mandasse, a tela ficaria esperando transcricao
# que nunca vem. quando o roveris entregar a transcricao, e so descomentar o send_json
# la embaixo que a tela liga o protocolo novo sozinha.
@app.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """
    Endpoint de WebSocket Fase 3 atualizado.
    Recebe chunks de áudio, salva e se comunica via protocolo de eventos (JSON).
    """
    await websocket.accept()
    print("[websocket] cliente conectou no tubo de streaming!")
    
    # Passo 5: Mandar um evento de status inicial pro front
    await websocket.send_text(json.dumps({
        "event": "agent_state",
        "state": "listening"
    }))
    
    caminho_audio = "audio_cliente_streaming.webm"
    
    try:
        with open(caminho_audio, "wb") as arquivo:
            while True:
                # O backend espera receber DADOS (bytes de áudio) ou TEXTO (JSON com comandos)
                # Vamos focar em receber os bytes de áudio primeiro (Passo 3)
                data = await websocket.receive_bytes()
                
                # Guarda o chunk
                arquivo.write(data)
                
                # Passo 4 (Simulado): Aqui o áudio iria pro pipeline em tempo real
                # Como o Roveris ainda não entregou, vamos só avisar o front
                
                # Passo 5: Devolvendo eventos
                # Exemplo: avisando o front que o agente está "processando" esse chunk
                await websocket.send_text(json.dumps({
                    "event": "agent_state",
                    "state": "processing"
                }))
                
    except WebSocketDisconnect:
        # Passo 6: Tratar desconexão
        print(f"[websocket] cliente desconectou da chamada.")
        print(f"[websocket] audio completo salvo em: {caminho_audio}")
        
        # --- MOCK DA IA ---
        # Quando o cliente desliga, a IA processaria tudo. 
        # Aqui você futuramente chamará o pipeline e o Ollama!


# --- front-end: o proprio fastapi entrega a pasta frontend na raiz ---
# esse mount fica POR ULTIMO de proposito: as rotas declaradas acima (/health, /teste,
# /api/v1/falar, /ws/falar) sao casadas antes, o resto cai nos arquivos da pasta frontend
PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=PASTA_FRONTEND, html=True), name="frontend")
