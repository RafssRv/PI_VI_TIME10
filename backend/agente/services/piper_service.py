import subprocess

def sintetizar_resposta(texto):
    modelo = "models/piper/pt_BR-cadu-medium.onnx"
    output = "audio/resposta.wav"

    processo = subprocess.Popen(
    [
        "piper",
        "--model",
        modelo,
        "--output_file",
        output
    ],
    stdin=subprocess.PIPE,
    text=True
    )

    processo.communicate(texto)

