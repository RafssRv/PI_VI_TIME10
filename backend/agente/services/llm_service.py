import requests

from config import MODELO_DO_OLLAMA, URL_DO_OLLAMA


def conversar(mensagens, formato=None):
    # Manda o prompt de sistema e a conversa para preservar o contexto dos turnos.
    # formato eh um json schema: o ollama obriga a resposta a seguir ele (texto livre se None)
    corpo = {
        "model": MODELO_DO_OLLAMA,
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

    resposta = requests.post(URL_DO_OLLAMA.rstrip("/") + "/api/chat", json=corpo, timeout=120)
    resposta.raise_for_status()

    return resposta.json()["message"]["content"]


def precarregar():
    # pedido sem prompt so carrega o modelo: a 1a duvida da chamada levava ~60 s, depois disso ~1 s
    requests.post(URL_DO_OLLAMA.rstrip("/") + "/api/generate",
                  json={"model": MODELO_DO_OLLAMA, "keep_alive": "30m"}, timeout=120).raise_for_status()
