import os
import subprocess
import sys
from pathlib import Path

# pasta "agente". os caminhos partem daqui pra funcionar rodando de qualquer pasta
PASTA_AGENTE = Path(__file__).resolve().parent.parent


def sintetizar_resposta(texto):
    modelo = PASTA_AGENTE / "models" / "piper" / "pt_BR-cadu-medium.onnx"
    output = PASTA_AGENTE / "audio" / "resposta.wav"
    output.parent.mkdir(exist_ok=True)

    # roda como "py -m piper" pq no windows o comando "piper" sozinho nem sempre eh achado.
    # o utf-8 eh pros acentos chegarem certos
    processo = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "piper",
        "--model",
        str(modelo),
        "--output_file",
        str(output)
    ],
    stdin=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    env={**os.environ, "PYTHONUTF8": "1"}
    )

    processo.communicate(texto)

    if processo.returncode != 0:
        raise RuntimeError(f"o piper falhou (codigo {processo.returncode})")

    return output
