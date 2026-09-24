from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
import json
import os
import shutil
from pathlib import Path
from fastapi.staticfiles import StaticFiles

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
    endpoint de websocket fase 3.
    recebe chunks de audio, junta tudo num arquivo so e guarda.
    """
    await websocket.accept()
    print("[websocket] cliente conectou no tubo de streaming!")

    # --- QUANDO A TRANSCRICAO ESTIVER PRONTA, DESCOMENTE ESTA LINHA ---
    # await websocket.send_json({"tipo": "pronto", "versao": 1})
    # ------------------------------------------------------------------

    # a gnt cria um arquivo e abre ele no modo "wb" (write bytes)
    # ou "ab" (append bytes). vamos de "wb" e manter ele aberto.
    caminho_audio = "audio_cliente_streaming.webm"
    formato_do_audio = None

    try:
        # abrimos o arquivo uma vez so, pra ir enchendo ele de dados
        with open(caminho_audio, "wb") as arquivo:
            while True:
                # receive() em vez de receive_bytes(): o receive_bytes estoura KeyError
                # quando chega um frame de TEXTO (a mensagem vem com a chave "text" e ele
                # procura "bytes"), e esse KeyError nao eh WebSocketDisconnect, entao
                # derrubava a conexao inteira. aqui a gente olha o que chegou e decide.
                mensagem = await websocket.receive()

                if mensagem["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(mensagem.get("code", 1000))

                pedaco = mensagem.get("bytes")
                if pedaco is not None:
                    # escreve o pedacinho no final do arquivo
                    arquivo.write(pedaco)
                    print(f"[websocket] recebi e guardei um chunk de {len(pedaco)} bytes")

                    # manda um textinho pro front so pra confirmar q chegou
                    await websocket.send_text("chunk guardado no backend!")
                    continue

                texto = mensagem.get("text")
                if texto is None:
                    continue

                try:
                    controle = json.loads(texto)
                except json.JSONDecodeError:
                    print(f"[websocket] texto que nao eh json, ignorei: {texto[:80]!r}")
                    continue

                tipo = controle.get("tipo")

                if tipo == "iniciar_chamada":
                    # a tela avisa em que formato ela vai gravar (webm/opus, mp4/aac...).
                    # a transcricao precisa disso pra saber como abrir o arquivo
                    formato_do_audio = controle.get("formato")
                    print(f"[websocket] chamada iniciada, formato do audio: {formato_do_audio}")

                elif tipo == "fim_da_fala":
                    # o cliente parou de falar: aqui entra a transcricao do turno
                    print(f"[websocket] fim da fala do turno {controle.get('turno')}")
                    # --- MOCK DA FASE 3 ---
                    # texto_do_cliente = roveris_transcrever(caminho_audio, formato_do_audio)
                    # resposta = nonato_responder(texto_do_cliente)
                    # await websocket.send_json({"tipo": "transcricao", "quem": "cliente", ...})
                    # ----------------------

                elif tipo == "resposta_tocada":
                    # a tela terminou de tocar a resposta e ja reabriu o microfone
                    print(f"[websocket] resposta do turno {controle.get('turno')} terminou de tocar")

                elif tipo == "encerrar_chamada":
                    print(f"[websocket] tela pediu pra encerrar: {controle.get('motivo')}")
                    # fecha o socket na mao: so sair da funcao nao manda o frame de close,
                    # e a tela ficaria esperando por um fim que nunca chega
                    await websocket.close()
                    break

                else:
                    print(f"[websocket] controle desconhecido, ignorei: {tipo!r}")

    except WebSocketDisconnect:
        # quando o cara desligar a chamada no front (ou fechar a aba), cai aqui
        print(f"[websocket] cliente desconectou.")

    print(f"[websocket] audio completo salvo em: {caminho_audio}")


# --- front-end: o proprio fastapi entrega a pasta frontend ---
PASTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/app", StaticFiles(directory=PASTA_FRONTEND, html=True), name="frontend")
