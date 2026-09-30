from services.llm_service import responder
from services.whisper_service import transcrever

texto=transcrever("audio/entrada.wav")

print("Transcricao: ")
print(texto)

resposta = responder(texto)

print("Resposta: ")
print(resposta)