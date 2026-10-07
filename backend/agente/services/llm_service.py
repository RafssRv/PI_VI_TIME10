import requests

def responder(texto):
    resposta = requests.post(
        "http://127.0.0.1:11434/api/generate",
        json={
            "model": "llama3.2:3b",
            "prompt": texto,
            "stream": False
        }
    )

    dados=resposta.json()

    return dados["response"]