from services.llm_service import responder
from services.whisper_service import transcrever
from services.piper_service import sintetizar_resposta


def processar_audio(caminho_audio):
    texto = transcrever(caminho_audio)

    print("Transcricao:")
    print(texto)

    resposta = responder(texto)

    sintetizar_resposta(resposta)

    print("Resposta:")
    print(resposta)

    return texto, resposta