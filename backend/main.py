from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import asyncio
import shutil
from pathlib import Path
from time import monotonic
from fastapi.staticfiles import StaticFiles

from atendimento import Atendimento
from turno_de_voz import atender_turno
from protocolo import (
    DURACAO_MAXIMA_CHAMADA_S, LIMITE_AUDIO_CHAMADA_BYTES, LIMITE_BLOCO_AUDIO_BYTES,
    VERSAO_PROTOCOLO, ErroProtocolo, validar_controle,
)

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

# Contrato completo em doc/protocolo-websocket.md.
@app.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """Recebe controles validados e áudio limitado por chamada."""
    await websocket.accept()
    prazo = monotonic() + DURACAO_MAXIMA_CHAMADA_S
    print("[websocket] cliente conectou no tubo de streaming!")
    await websocket.send_json({"tipo": "pronto", "versao_protocolo": VERSAO_PROTOCOLO})
    caminho_audio = "audio_cliente_streaming.webm"
    iniciada = False
    ultimo_turno = 0
    bytes_no_ultimo_turno = 0
    # O cabeçalho do contêiner só vem no primeiro bloco; preserve até o limite.
    audio_da_chamada = bytearray()
    amostra_inicio = 0
    atendimento = Atendimento()

    try:
        with open(caminho_audio, "wb") as arquivo:
            while True:
                restante = prazo - monotonic()
                if restante <= 0:
                    raise ErroProtocolo("A chamada atingiu o tempo máximo permitido.")
                try:
                    mensagem = await asyncio.wait_for(websocket.receive(), timeout=restante)
                except asyncio.TimeoutError:
                    raise ErroProtocolo("A chamada atingiu o tempo máximo permitido.") from None
                if mensagem["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(mensagem.get("code", 1000))
                if monotonic() >= prazo:
                    raise ErroProtocolo("A chamada atingiu o tempo máximo permitido.")

                pedaco = mensagem.get("bytes")
                if pedaco is not None:
                    if not iniciada:
                        raise ErroProtocolo("Envie iniciar_chamada antes do áudio.")
                    if len(pedaco) > LIMITE_BLOCO_AUDIO_BYTES:
                        raise ErroProtocolo("O bloco de áudio ultrapassou o limite permitido.", 1009)
                    if len(audio_da_chamada) + len(pedaco) > LIMITE_AUDIO_CHAMADA_BYTES:
                        raise ErroProtocolo("A chamada atingiu o limite de áudio permitido.", 1009)
                    arquivo.write(pedaco)
                    audio_da_chamada.extend(pedaco)
                    print(f"[websocket] recebi e guardei um chunk de {len(pedaco)} bytes")
                    await websocket.send_text("chunk guardado no backend!")
                    continue

                texto = mensagem.get("text")
                if texto is None:
                    continue

                controle = validar_controle(texto)
                tipo = controle["tipo"]
                if tipo == "iniciar_chamada":
                    if iniciada:
                        raise ErroProtocolo("A chamada já foi iniciada.")
                    iniciada = True
                    continue
                if tipo == "encerrar_chamada":
                    await websocket.close()
                    break
                if not iniciada:
                    raise ErroProtocolo("Envie iniciar_chamada antes dos demais controles.")

                turno = controle["turno"]
                if tipo == "fim_da_fala":
                    if turno <= ultimo_turno:
                        raise ErroProtocolo("O turno precisa ser maior que o último turno processado.")
                    if len(audio_da_chamada) == bytes_no_ultimo_turno:
                        raise ErroProtocolo("O turno precisa conter áudio novo.")
                    ultimo_turno = turno
                    bytes_no_ultimo_turno = len(audio_da_chamada)
                    # Não interromper uma gravação no banco quando o prazo vencer.
                    # O loop encerra a recepção assim que o turno em andamento terminar.
                    amostra_inicio = await atender_turno(
                        websocket, audio_da_chamada, amostra_inicio, turno, atendimento)
                else:
                    # Avisos de reprodução/timeout podem chegar atrasados, mas não do futuro.
                    if turno > ultimo_turno:
                        raise ErroProtocolo("O aviso se refere a um turno ainda não processado.")

    except ErroProtocolo as erro:
        await websocket.send_json({"tipo": "erro", "onde": "protocolo",
                                   "mensagem": str(erro), "fatal": True})
        await websocket.close(code=erro.codigo)
    except WebSocketDisconnect:
        print("[websocket] cliente desconectou da chamada.")


# --- front-end: o proprio fastapi entrega a pasta frontend na raiz ---
# esse mount fica POR ULTIMO de proposito: as rotas declaradas acima (/health, /teste,
# /api/v1/falar, /ws/falar) sao casadas antes, o resto cai nos arquivos da pasta frontend
PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=PASTA_FRONTEND, html=True), name="frontend")
