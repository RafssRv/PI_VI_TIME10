from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging
from tempfile import TemporaryFile
from time import monotonic

from atendimento import Atendimento
from turno_de_voz import atender_turno, saudar
from monitor import monitor
from protocolo import (
    DURACAO_MAXIMA_CHAMADA_S, LIMITE_AUDIO_CHAMADA_BYTES, LIMITE_BLOCO_AUDIO_BYTES,
    VERSAO_PROTOCOLO, ErroProtocolo, validar_controle,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Os controles de entrada são validados por protocolo.py.
@router.websocket("/ws/falar")
async def websocket_audio(websocket: WebSocket):
    """Recebe controles validados e áudio limitado por chamada."""
    await websocket.accept()
    prazo = monotonic() + DURACAO_MAXIMA_CHAMADA_S
    atendimento = Atendimento()
    logger.info("chamada=%s etapa=conexao status=aberta", atendimento.id_chamada)
    monitor.iniciar_chamada(atendimento.id_chamada)
    await websocket.send_json({"tipo": "pronto", "versao_protocolo": VERSAO_PROTOCOLO})
    iniciada = False
    ultimo_turno = 0
    bytes_no_ultimo_turno = 0
    # O cabeçalho do contêiner só vem no primeiro bloco; preserve até o limite.
    audio_da_chamada = bytearray()
    amostra_inicio = 0
    # so o encerrar_chamada do cliente eh um fim normal; o resto fica marcado no monitor
    motivo = "conexao_perdida"

    try:
        # Cada conexao possui sua gravacao, removida ao terminar a chamada.
        with TemporaryFile() as arquivo:
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
                    logger.debug("chamada=%s etapa=audio bytes=%s", atendimento.id_chamada, len(pedaco))
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
                    monitor.atualizar_etapa(atendimento.id_chamada, "saudando", 0)
                    await saudar(websocket, atendimento)
                    continue
                if tipo == "encerrar_chamada":
                    motivo = "finalizada"
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
                    monitor.atualizar_etapa(atendimento.id_chamada, "transcrevendo", turno)
                    amostra_inicio = await atender_turno(
                        websocket, audio_da_chamada, amostra_inicio, turno, atendimento)
                else:
                    # Avisos de reprodução/timeout podem chegar atrasados, mas não do futuro.
                    if turno > ultimo_turno:
                        raise ErroProtocolo("O aviso se refere a um turno ainda não processado.")

    except ErroProtocolo as erro:
        motivo = "erro_protocolo"
        logger.warning("chamada=%s turno=%s etapa=protocolo categoria=validacao",
                       atendimento.id_chamada, ultimo_turno)
        await websocket.send_json({"tipo": "erro", "onde": "protocolo",
                                   "mensagem": str(erro), "fatal": True})
        await websocket.close(code=erro.codigo)
    except WebSocketDisconnect:
        logger.info("chamada=%s etapa=conexao status=encerrada", atendimento.id_chamada)
    except Exception:
        motivo = "erro_servidor"
        # Exceções de drivers/modelos podem conter a fala ou parâmetros SQL.
        logger.warning("chamada=%s turno=%s etapa=chamada categoria=inesperada",
                       atendimento.id_chamada, ultimo_turno)
        try:
            await websocket.send_json({"tipo": "erro", "onde": "servidor",
                                       "mensagem": "Não consegui continuar a chamada.", "fatal": True})
            await websocket.close(code=1011)
        except Exception:
            logger.warning("chamada=%s etapa=conexao categoria=envio_erro", atendimento.id_chamada)
    finally:
        monitor.encerrar_chamada(atendimento.id_chamada, motivo, atendimento.ultimo_pedido_id)
