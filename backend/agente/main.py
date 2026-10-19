"""Arquivo entra, arquivo sai: python -m backend.agente.main entrada.wav --saida resposta.wav."""

import argparse
from pathlib import Path


def processar_audio(caminho_audio, caminho_saida=None):
    if not Path(caminho_audio).is_file():
        raise FileNotFoundError("Áudio de entrada não encontrado: {}".format(caminho_audio))
    # Imports tardios permitem --help sem carregar os modelos.
    if __package__:
        from .services.llm_service import responder
        from .services.whisper_service import transcrever
        from .services.piper_service import sintetizar_resposta
    else:
        from services.llm_service import responder
        from services.whisper_service import transcrever
        from services.piper_service import sintetizar_resposta
    if caminho_saida is not None and Path(caminho_audio).resolve() == Path(caminho_saida).resolve():
        raise ValueError("Entrada e saída precisam ser arquivos diferentes.")
    texto = transcrever(str(caminho_audio))
    print("Transcrição:", texto)
    resposta = responder(texto)
    sintetizar_resposta(resposta, caminho_saida)
    print("Resposta:", resposta)
    return texto, resposta


def main():
    parser = argparse.ArgumentParser(description="Whisper -> Ollama/Llama -> Piper, executados localmente.")
    parser.add_argument("entrada", type=Path, help="Arquivo de áudio do cliente")
    parser.add_argument("--saida", type=Path, default=Path("resposta.wav"), help="WAV gerado (padrão: resposta.wav)")
    args = parser.parse_args()
    try:
        processar_audio(args.entrada, args.saida)
    except Exception as erro:
        parser.exit(1, "Falha no pipeline: {}\n".format(erro))
    print("Áudio salvo em:", args.saida.resolve())


if __name__ == "__main__":
    main()
