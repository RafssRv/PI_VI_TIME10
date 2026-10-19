"""Carrega o modelo só na primeira transcrição, sem download no import do servidor."""

import os
from threading import Lock

from faster_whisper import WhisperModel

_modelo = None
_lock = Lock()


def transcrever(caminho_audio):
    global _modelo
    with _lock:
        if _modelo is None:
            _modelo = WhisperModel(os.getenv("WHISPER_MODEL", "base"), device="cpu", compute_type="int8")
        segmentos, _ = _modelo.transcribe(caminho_audio, language="pt")
        return "".join(segmento.text for segmento in segmentos).strip()
