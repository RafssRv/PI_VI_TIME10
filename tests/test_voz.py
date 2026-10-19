"""Regressões do pipeline: erros, contexto, isolamento e áudio PCM real."""

import asyncio
import io
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from agente.services import audio_service, llm_service, piper_service
import turno_de_voz


def wav_bytes(amostras=16000, taxa=16000):
    arquivo = io.BytesIO()
    with wave.open(arquivo, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(taxa)
        wav.writeframes(b"\x01\x00" * amostras)
    return arquivo.getvalue()


def test_audio_decodifica_e_recorta_sem_repetir_fala(tmp_path):
    audio = wav_bytes()
    caminho, fim = audio_service.salvar_fala_em_wav(audio, 4000, tmp_path / "turno.wav")
    assert fim == 16000
    with wave.open(str(caminho)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) == (16000, 1, 2, 12000)


def test_audio_rejeita_turno_sem_amostras(tmp_path):
    with pytest.raises(ValueError, match="Nenhuma nova"):
        audio_service.salvar_fala_em_wav(wav_bytes(), 16000, tmp_path / "turno.wav")


def test_audio_rejeita_arquivo_corrompido(tmp_path):
    with pytest.raises(Exception):
        audio_service.salvar_fala_em_wav(b"nao e audio", 0, tmp_path / "turno.wav")


def test_llm_envia_prompt_contexto_e_timeout(monkeypatch):
    chamadas = []

    def post(url, **kwargs):
        chamadas.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"content": "Olá, Ana."}})

    monkeypatch.setattr(llm_service.requests, "post", post)
    historico = []
    llm_service.responder("Meu nome é Ana", historico)
    llm_service.responder("Qual é meu nome?", historico)
    mensagens = chamadas[1][1]["json"]["messages"]
    assert mensagens[0] == {"role": "system", "content": llm_service.PROMPT_SISTEMA}
    assert mensagens[1]["content"] == "Meu nome é Ana"
    assert chamadas[0][1]["timeout"] == (5, 120)
    assert len(historico) == 4


@pytest.mark.parametrize("dados", [{"error": "modelo ausente"}, {"message": {"content": " "}}, {"message": {"content": 10}}])
def test_resposta_invalida_nao_corrompe_historico(monkeypatch, dados):
    monkeypatch.setattr(llm_service.requests, "post", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: dados))
    historico = []
    with pytest.raises(ValueError):
        llm_service.responder("Oi", historico)
    assert historico == []


def test_llm_verifica_status_http(monkeypatch):
    def falhar():
        raise requests.HTTPError("503")
    monkeypatch.setattr(llm_service.requests, "post", lambda *a, **k: SimpleNamespace(raise_for_status=falhar))
    with pytest.raises(requests.HTTPError):
        llm_service.responder("Oi")


def test_piper_nao_aceita_texto_vazio():
    with pytest.raises(ValueError):
        piper_service.sintetizar_resposta(" ")


class Socket:
    def __init__(self):
        self.mensagens = []

    async def send_json(self, mensagem):
        self.mensagens.append(mensagem)

    async def send_bytes(self, mensagem):
        self.mensagens.append(mensagem)


def test_timeout_da_funcao_nao_e_confundido_com_heartbeat():
    def falha():
        raise TimeoutError("tempo esgotado da etapa")

    async def executar():
        with pytest.raises(TimeoutError, match="etapa"):
            await asyncio.wait_for(turno_de_voz.rodar_sem_travar(Socket(), 1, "pensando", falha), timeout=1)

    asyncio.run(executar())


def agente_falso(monkeypatch, falha=None):
    caminhos = []

    def salvar(audio, inicio, destino):
        destino.write_bytes(wav_bytes())
        caminhos.append(destino)
        return destino, 16000

    def transcrever(caminho):
        if falha == "transcricao":
            raise RuntimeError("transcrição indisponível")
        return "" if falha == "silencio" else "Olá"

    def responder(texto, historico):
        if falha == "llm":
            raise requests.Timeout()
        return "Olá, como posso ajudar?"

    def sintetizar(texto, destino):
        if falha == "piper":
            raise RuntimeError("síntese indisponível")
        destino.write_bytes(wav_bytes())
        caminhos.append(destino)
        return destino

    monkeypatch.setattr(turno_de_voz, "carregar_agente", lambda: {"salvar_fala_em_wav": salvar, "transcrever": transcrever, "responder": responder, "sintetizar_resposta": sintetizar})
    return caminhos


@pytest.mark.parametrize("falha,onde", [("transcricao", "transcricao"), ("silencio", "transcricao"), ("llm", "ollama"), ("piper", "piper")])
def test_falha_reabre_microfone_e_limpa_arquivos(monkeypatch, falha, onde):
    caminhos = agente_falso(monkeypatch, falha)
    ws = Socket()
    fim = asyncio.run(turno_de_voz.atender_turno(ws, bytearray(b"audio"), 0, 1, []))
    assert fim == 16000
    assert ws.mensagens[-2]["onde"] == onde
    assert ws.mensagens[-1] == {"tipo": "estado", "etapa": "ouvindo"}
    assert all(not p.exists() for p in caminhos)


def test_chamadas_simultaneas_usam_arquivos_distintos(monkeypatch):
    caminhos = agente_falso(monkeypatch)

    def chamar(numero):
        ws = Socket()
        asyncio.run(turno_de_voz.atender_turno(ws, bytearray(b"audio"), 0, numero, []))
        assert ws.mensagens[-1]["tipo"] == "fim_audio"
        assert any(isinstance(m, bytes) for m in ws.mensagens)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(chamar, (1, 2)))
    assert len(set(p.parent for p in caminhos)) == 2
    assert all(not p.exists() for p in caminhos)
