"""Conversa local no Ollama. O histórico é fornecido pelo chamador, nunca global."""

import os
from pathlib import Path

import requests

PROMPT_SISTEMA = (Path(__file__).resolve().parent.parent / "prompt_sistema.txt").read_text(encoding="utf-8")
MAX_MENSAGENS = 20


def responder(texto, historico=None):
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("A fala do cliente está vazia.")
    anteriores = list(historico or [])[-MAX_MENSAGENS:]
    mensagem = {"role": "user", "content": texto.strip()}
    resposta = requests.post(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat",
        json={
            "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            "messages": [{"role": "system", "content": PROMPT_SISTEMA}, *anteriores, mensagem],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 160},
        },
        timeout=(5, 120),
    )
    resposta.raise_for_status()
    dados = resposta.json()
    conteudo = dados.get("message", {}).get("content")
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise ValueError("Ollama devolveu uma resposta vazia ou inválida.")
    conteudo = conteudo.strip()
    if historico is not None:
        historico.extend([mensagem, {"role": "assistant", "content": conteudo}])
        del historico[:-MAX_MENSAGENS]
    return conteudo
