import requests


def conversar(mensagens, formato=None):
    # Manda o prompt de sistema e a conversa para preservar o contexto dos turnos.
    # formato eh um json schema: o ollama obriga a resposta a seguir ele (texto livre se None)
    corpo = {
        "model": "llama3.2:3b",
        "messages": mensagens,
        "stream": False,
        # sem isso o ollama descarrega o modelo apos 5 min parado e a proxima fala paga o carregamento
        "keep_alive": "30m"
    }
    if formato is not None:
        corpo["format"] = formato
        # temperatura baixa: pra extrair o pedido a gnt quer o mesmo resultado sempre.
        # o json do pedido eh curto, o limite so evita o modelo se alongar no processador
        corpo["options"] = {"temperature": 0.2, "num_predict": 400}

    resposta = requests.post("http://127.0.0.1:11434/api/chat", json=corpo, timeout=120)
    resposta.raise_for_status()

    return resposta.json()["message"]["content"]
