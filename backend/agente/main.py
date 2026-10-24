from services.llm_service import responder
from services.whisper_service import transcrever
from services.piper_service import sintetizar_resposta


def processar_audio(caminho_audio):
    texto = transcrever(caminho_audio)

    resposta = responder(texto)

    sintetizar_resposta(resposta)

    return texto, resposta
