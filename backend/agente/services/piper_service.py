import os
import subprocess
import sys
from pathlib import Path

# caminhos montados a partir da pasta "agente", e nao de onde o terminal esta.
# assim funciona tanto rodando de dentro de agente quanto pelo servidor (que roda em backend)
PASTA_AGENTE = Path(__file__).resolve().parent.parent


def sintetizar_resposta(texto):
    modelo = PASTA_AGENTE / "models" / "piper" / "pt_BR-cadu-medium.onnx"
    output = PASTA_AGENTE / "audio" / "resposta.wav"
    output.parent.mkdir(exist_ok=True)

    # "py -m piper" em vez de so "piper": no windows o comando piper nem sempre esta no PATH
    # PYTHONUTF8=1 garante que os acentos do portugues cheguem certos no piper
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
