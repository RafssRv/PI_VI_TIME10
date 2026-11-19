import os
import shutil
import threading
import wave
from pathlib import Path

# Configura o caminho de dados foneticos do espeak-ng.
# No Windows, caminhos contendo acentos (ex: "Área de Trabalho") causam erro de
# "Illegal byte sequence" ou "No such file" na lib C do espeak-ng.
# Copiamos para o %LOCALAPPDATA% (sem acentos) se necessario.
def _garantir_dados_espeak():
    try:
        import piper
        origem = Path(piper.__file__).parent / "espeak-ng-data"
        if not origem.exists():
            return

        # Verifica se o caminho original contem caracteres nao-ascii
        str_origem = str(origem)
        try:
            str_origem.encode("ascii")
            caminho_final = origem
        except UnicodeEncodeError:
            # Tem acento no caminho: usa pasta segura no LOCALAPPDATA
            base_local = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "C:\\"
            destino = Path(base_local) / "pizzaria-espeak-ng-data"
            if not (destino / "phontab").exists():
                shutil.copytree(origem, destino, dirs_exist_ok=True)
            caminho_final = destino

        os.environ["ESPEAK_DATA_PATH"] = str(caminho_final)
    except Exception:
        pass

_garantir_dados_espeak()

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
