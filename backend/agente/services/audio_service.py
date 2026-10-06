import io
import wave
from pathlib import Path

import av

# pasta onde ficam os audios da conversa (cliente.wav e resposta.wav)
PASTA_AUDIO = Path(__file__).resolve().parent.parent / "audio"

# o whisper usa audio mono em 16 kHz, entao ja salva assim
TAXA_AMOSTRAGEM = 16000


def decodificar_para_pcm(audio_da_chamada):
    """
    transforma o audio da chamada inteira (webm, q eh o q o navegador manda)
    em audio "cru", q da pra recortar e salvar como wav.

    tem q ser a chamada inteira pq so o primeiro pedaco do webm tem o cabecalho,
    sem ele os outros pedacos nao abrem
    """
    container = av.open(io.BytesIO(audio_da_chamada))
    conversor = av.AudioResampler(format="s16", layout="mono", rate=TAXA_AMOSTRAGEM)

    pcm = bytearray()
    try:
        for pacote in container.demux(audio=0):
            try:
                frames = pacote.decode()
            except av.error.FFmpegError:
                # pedaco estragado: pula ele e continua
                continue
            for frame in frames:
                for convertido in conversor.resample(frame):
                    pcm.extend(bytes(convertido.planes[0])[: convertido.samples * 2])
    except av.error.FFmpegError:
        # o ultimo pedaco pode vir cortado, aproveita o q deu pra ler
        pass
    finally:
        container.close()

    return bytes(pcm)


def salvar_fala_em_wav(audio_da_chamada, amostra_inicio):
    """
    salva so a fala atual em agente/audio/cliente.wav.
    amostra_inicio eh onde a fala anterior parou (tipo um marcador de pagina).
    devolve o caminho do wav e onde essa fala parou, pro proximo turno
    """
    pcm = decodificar_para_pcm(audio_da_chamada)

    # cada amostra ocupa 2 bytes
    fala_atual = pcm[amostra_inicio * 2:]
    amostra_fim = len(pcm) // 2

    PASTA_AUDIO.mkdir(exist_ok=True)
    caminho = PASTA_AUDIO / "cliente.wav"

    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_AMOSTRAGEM)
        arquivo.writeframes(fala_atual)

    return caminho, amostra_fim
