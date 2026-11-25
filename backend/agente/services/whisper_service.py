import os
import logging

import numpy as np
from faster_whisper import WhisperModel
from interpretacao import juntar_segmentos

logger = logging.getLogger(__name__)

nome_modelo = os.environ.get("WHISPER_MODEL", "base")
device_solicitado = os.environ.get("WHISPER_DEVICE", "cuda")


def _carregar(device, compute_type):
    try:
        # modelo ja baixado nao pergunta pro huggingface: a apresentacao pode estar sem internet
        modelo = WhisperModel(nome_modelo, device=device, compute_type=compute_type, local_files_only=True)
    except Exception:
        modelo = WhisperModel(nome_modelo, device=device, compute_type=compute_type)
    # carregar na gpu nao garante transcrever: com placa nvidia e sem a cublas do cuda 12, o erro
    # so aparecia na primeira fala do cliente e derrubava todos os turnos. 1 s de silencio testa agora
    list(modelo.transcribe(np.zeros(16000, dtype=np.float32), language="pt")[0])
    return modelo


# Tenta a GPU (CUDA); se ela não carregar ou não conseguir transcrever, usa a CPU
try:
    if device_solicitado == "cuda":
        modelo = _carregar("cuda", "float16")
        logger.info("[whisper] Modelo '%s' carregado com sucesso na GPU (CUDA float16).", nome_modelo)
    else:
        modelo = _carregar("cpu", "int8")
        logger.info("[whisper] Modelo '%s' carregado na CPU.", nome_modelo)
except Exception as erro:
    logger.warning("[whisper] A GPU não funcionou (%s). Utilizando CPU como fallback.", type(erro).__name__)
    modelo = _carregar("cpu", "int8")


def transcrever(caminho_audio, dica=None):
    # a dica diz o que esperar ouvir: sem ela, "coca-cola" virava "foca escona" no modelo base
    segmentos, info = modelo.transcribe(
        caminho_audio,
        language="pt",
        initial_prompt=dica
    )

    return juntar_segmentos(segmentos)
