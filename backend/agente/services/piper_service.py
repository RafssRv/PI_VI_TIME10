import os
import subprocess
import sys
from pathlib import Path

# pasta "agente". os caminhos partem daqui pra funcionar rodando de qualquer pasta
PASTA_AGENTE = Path(__file__).resolve().parent.parent


def sintetizar_resposta(texto, caminho_saida=None):
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("O texto da resposta está vazio.")
    modelo = PASTA_AGENTE / "models" / "piper" / "pt_BR-cadu-medium.onnx"
    output = Path(caminho_saida) if caminho_saida is not None else PASTA_AGENTE / "audio" / "resposta.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not modelo.is_file():
        raise FileNotFoundError("Modelo de voz do Piper não encontrado: {}".format(modelo))

    # roda como "py -m piper" pq no windows o comando "piper" sozinho nem sempre eh achado.
    # o utf-8 eh pros acentos chegarem certos
    subprocess.run(
    [
        sys.executable,
        "-m",
        "piper",
        "--model",
        str(modelo),
        "--output_file",
        str(output)
    ],
    input=texto,
    text=True,
    encoding="utf-8",
    env={**os.environ, "PYTHONUTF8": "1"},
    capture_output=True,
    timeout=120,
    check=True,
    )

    if not output.is_file() or output.stat().st_size <= 44:
        raise RuntimeError("O Piper não gerou um áudio de resposta válido.")
    return output
