import threading
import wave
from pathlib import Path

# pasta "agente". os caminhos partem daqui pra funcionar rodando de qualquer pasta
PASTA_AGENTE = Path(__file__).resolve().parent.parent

# a voz fica carregada: abrir um processo novo a cada fala custava uns 4,5 s, e assim fica abaixo de 1 s.
# a trava pq duas chamadas ao mesmo tempo nao podem usar a voz juntas
_voz = None
_trava = threading.Lock()


def _carregar_voz():
    global _voz
    if _voz is None:
        from piper import PiperVoice
        _voz = PiperVoice.load(str(PASTA_AGENTE / "models" / "piper" / "pt_BR-cadu-medium.onnx"))
    return _voz


def sintetizar_resposta(texto, caminho=None):
    output = Path(caminho) if caminho is not None else PASTA_AGENTE / "audio" / "resposta.wav"
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with _trava:
            voz = _carregar_voz()
            with wave.open(str(output), "wb") as arquivo:
                voz.synthesize_wav(texto, arquivo)
    except Exception:
        # o erro original pode repetir a fala do cliente: nao vai pra mensagem nem pro log
        raise RuntimeError("o piper falhou") from None

    return output
