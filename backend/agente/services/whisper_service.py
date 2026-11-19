import os
import logging
from faster_whisper import WhisperModel
from interpretacao import juntar_segmentos

logger = logging.getLogger(__name__)

nome_modelo = os.environ.get("WHISPER_MODEL", "base")
device_solicitado = os.environ.get("WHISPER_DEVICE", "cuda")

# Tenta carregar na GPU (CUDA); se falhar (ex: máquina sem placa NVIDIA), faz fallback suave para CPU
try:
    if device_solicitado == "cuda":
        modelo = WhisperModel(nome_modelo, device="cuda", compute_type="float16")
        logger.info("[whisper] Modelo '%s' carregado com sucesso na GPU (CUDA float16).", nome_modelo)
    else:
        modelo = WhisperModel(nome_modelo, device="cpu", compute_type="int8")
        logger.info("[whisper] Modelo '%s' carregado na CPU.", nome_modelo)
except Exception as erro:
    logger.warning("[whisper] Falha ao carregar na GPU (%s). Utilizando CPU como fallback.", erro)
    modelo = WhisperModel(nome_modelo, device="cpu", compute_type="int8")


def transcrever(caminho_audio, dica=None):
    # a dica diz o que esperar ouvir: sem ela, "coca-cola" virava "foca escona" no modelo base
    segmentos, info = modelo.transcribe(
        caminho_audio,
        language="pt",
        initial_prompt=dica
    )

    return juntar_segmentos(segmentos)
