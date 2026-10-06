import io
import wave
from pathlib import Path

import av

# pasta onde o agente guarda os audios da conversa (cliente.wav e resposta.wav)
PASTA_AUDIO = Path(__file__).resolve().parent.parent / "audio"

# o whisper trabalha com audio mono em 16 kHz, entao a gente ja salva nesse formato
TAXA_AMOSTRAGEM = 16000


def decodificar_para_pcm(audio_da_chamada):
    """
    recebe TODOS os bytes que o navegador mandou desde o comeco da chamada (webm)
    e devolve o audio "cru" (pcm 16 bits, mono, 16 kHz).

    por que a chamada inteira e nao so a fala atual: o cabecalho do webm so vem no
    primeiro pedaco que o navegador manda. os pedacos seguintes sozinhos nao abrem.
    """
    container = av.open(io.BytesIO(audio_da_chamada))
    conversor = av.AudioResampler(format="s16", layout="mono", rate=TAXA_AMOSTRAGEM)

    pcm = bytearray()
    try:
        for pacote in container.demux(audio=0):
            try:
                frames = pacote.decode()
            except av.error.FFmpegError:
                # pacote estragado (ex.: o ultimo, cortado no meio): pula e segue com o resto
                continue
            for frame in frames:
                for convertido in conversor.resample(frame):
                    pcm.extend(bytes(convertido.planes[0])[: convertido.samples * 2])
    except av.error.FFmpegError:
        # o arquivo acabou no meio de um pedaco. o que deu pra ler a gente aproveita
        pass
    finally:
        container.close()

    return bytes(pcm)


def salvar_fala_em_wav(audio_da_chamada, amostra_inicio):
    """
    salva so a fala do turno atual em agente/audio/cliente.wav.

    amostra_inicio = onde a fala anterior terminou (0 no primeiro turno).
    devolve o caminho do wav e onde essa fala terminou, pra usar no proximo turno.
    """
    pcm = decodificar_para_pcm(audio_da_chamada)

    # cada amostra tem 2 bytes (16 bits)
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
