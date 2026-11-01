"""Isolamento de arquivos entre chamadas, sem banco e sem modelos externos."""

import asyncio
import io
import struct
import threading
import wave
from pathlib import Path

import pytest

import turno_de_voz
from agente.services import audio_service


def audio_wav(amostra):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<h", amostra) * 1600)
    return buffer.getvalue()


@pytest.mark.parametrize("etapa_concorrente", ["transcricao", "sintese"])
def test_chamadas_simultaneas_nao_trocam_audio(tmp_path, monkeypatch, etapa_concorrente):
    monkeypatch.setattr(audio_service, "PASTA_AUDIO", tmp_path)
    barreira = threading.Barrier(2)
    caminhos = []

    def transcrever(caminho):
        caminhos.append(Path(caminho))
        if etapa_concorrente == "transcricao":
            barreira.wait(timeout=5)
        with wave.open(str(caminho)) as wav:
            return str(struct.unpack("<h", wav.readframes(1))[0])

    def sintetizar(texto, caminho=None):
        destino = Path(caminho) if caminho else tmp_path / "resposta.wav"
        destino.write_bytes(texto.encode())
        caminhos.append(destino)
        if etapa_concorrente == "sintese":
            barreira.wait(timeout=5)
        return destino

    class Socket:
        def __init__(self):
            self.audios = []

        async def send_json(self, mensagem):
            pass

        async def send_bytes(self, dados):
            self.audios.append(dados)

    class Atendimento:
        def responder(self, texto):
            return texto

    monkeypatch.setattr(turno_de_voz, "_agente", {
        "salvar_fala_em_wav": audio_service.salvar_fala_em_wav,
        "transcrever": transcrever,
        "sintetizar_resposta": sintetizar,
    })
    primeira, segunda = Socket(), Socket()

    async def executar():
        return await asyncio.gather(
            turno_de_voz.atender_turno(primeira, audio_wav(111), 0, 1, Atendimento()),
            turno_de_voz.atender_turno(segunda, audio_wav(222), 0, 1, Atendimento()),
        )

    fins = asyncio.run(executar())
    assert primeira.audios == [b"111"]
    assert segunda.audios == [b"222"]
    assert fins == [1600, 1600]
    assert all(not caminho.exists() for caminho in caminhos)


def test_nova_chamada_preserva_gravacao_anterior(tmp_path, monkeypatch):
    import main

    monkeypatch.chdir(tmp_path)
    anterior = tmp_path / "audio_cliente_streaming.webm"
    anterior.write_bytes(b"evidencia anterior")
    monkeypatch.setattr(main, "Atendimento", object)

    class Socket:
        async def accept(self):
            pass

        async def send_json(self, mensagem):
            pass

        async def receive(self):
            return {"type": "websocket.disconnect", "code": 1000}

    asyncio.run(main.websocket_audio(Socket()))
    assert anterior.read_bytes() == b"evidencia anterior"


def test_transcricoes_vazias_recebem_orientacao_em_voz_sem_modelo(tmp_path, monkeypatch):
    from atendimento import Atendimento

    falas, eventos = [], []

    def sintetizar(texto, caminho):
        falas.append(texto)
        caminho.write_bytes(audio_wav(111))
        return caminho

    class Socket:
        async def send_json(self, mensagem):
            eventos.append(mensagem)

        async def send_bytes(self, dados):
            pass

    def nao_chamar(*args, **kwargs):
        raise AssertionError("Transcrição vazia não deve chamar modelo nem banco")

    atendimento = Atendimento(abrir_sessao=nao_chamar, conversar=nao_chamar)
    monkeypatch.setattr(turno_de_voz, "_agente", {
        "salvar_fala_em_wav": audio_service.salvar_fala_em_wav,
        "transcrever": lambda caminho: "",
        "sintetizar_resposta": sintetizar,
    })
    for turno in (1, 2):
        asyncio.run(turno_de_voz.atender_turno(Socket(), audio_wav(111), 0, turno, atendimento))
    assert len(falas) == 2 and falas[0] != falas[1]
    assert all("?" in fala for fala in falas)
    assert len([e for e in eventos if e["tipo"] == "fim_audio"]) == 2
