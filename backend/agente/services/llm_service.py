import requests


def conversar(mensagens, formato=None):
    # Manda o prompt de sistema e a conversa para preservar o contexto dos turnos.
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
