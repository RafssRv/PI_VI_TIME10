from faster_whisper import WhisperModel

modelo = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)


def transcrever(caminho_audio):
    segmentos, info = modelo.transcribe(caminho_audio)


    texto_completo = ""

    for segmento in segmentos:
        texto_completo += segmento.text

    return texto_completo