from services.llm_service import responder
from services.whisper_service import transcrever
from services.piper_service import sintetizar_resposta

texto=transcrever("audio/entrada.wav")

resposta = responder(texto)

sintetizar_resposta(resposta)

