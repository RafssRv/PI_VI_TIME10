import os

from faster_whisper import WhisperModel

from interpretacao import juntar_segmentos

modelo = WhisperModel(
    os.environ.get("WHISPER_MODEL", "base"),
    device="cpu",
    compute_type="int8"
)


def transcrever(caminho_audio, dica=None):
    # a dica diz o que esperar ouvir: sem ela, "coca-cola" virava "foca escona" no modelo base
    segmentos, info = modelo.transcribe(
        caminho_audio,
        language="pt",
        initial_prompt=dica
        )

    return juntar_segmentos(segmentos)
