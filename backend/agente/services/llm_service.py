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


def conversar(mensagens, formato=None):
    # igual o responder, mas manda a conversa inteira (com o prompt de sistema na frente),
    # pro modelo lembrar do q ja foi dito nos turnos anteriores.
    # formato eh um json schema: o ollama obriga a resposta a seguir ele (texto livre se None)
    corpo = {
        "model": "llama3.2:3b",
        "messages": mensagens,
        "stream": False
    }
    if formato is not None:
        corpo["format"] = formato
        # temperatura baixa: pra extrair o pedido a gnt quer o mesmo resultado sempre
        corpo["options"] = {"temperature": 0.2}

    resposta = requests.post("http://127.0.0.1:11434/api/chat", json=corpo, timeout=120)
    resposta.raise_for_status()

    return resposta.json()["message"]["content"]