"""
carregamento do whisper: placa nvidia sem a cublas do cuda 12 carregava "na gpu" e falhava em
toda fala do cliente. o teste de 1 s de silencio no carregamento manda para a cpu antes disso.
"""

import importlib
import sys
import types

import pytest


def _carregar_com(monkeypatch, gpu_transcreve, tem_cache=True):
    criados = []

    class ModeloFalso:
        def __init__(self, nome, device, compute_type, local_files_only=False):
            if local_files_only and not tem_cache:
                raise OSError("sem o modelo no cache")
            self.device = device
            self.local_files_only = local_files_only
            criados.append(self)

        def transcribe(self, audio, **opcoes):
            if self.device == "cuda" and not gpu_transcreve:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter([]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=ModeloFalso))
    monkeypatch.delitem(sys.modules, "agente.services.whisper_service", raising=False)
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    return importlib.import_module("agente.services.whisper_service"), criados


def test_gpu_que_nao_transcreve_cai_para_a_cpu(monkeypatch):
    servico, _ = _carregar_com(monkeypatch, gpu_transcreve=False)
    assert servico.modelo.device == "cpu"


def test_gpu_que_funciona_continua_na_gpu(monkeypatch):
    servico, _ = _carregar_com(monkeypatch, gpu_transcreve=True)
    assert servico.modelo.device == "cuda"


@pytest.mark.parametrize("tem_cache", [True, False])
def test_usa_o_cache_antes_de_ir_para_a_internet(monkeypatch, tem_cache):
    servico, criados = _carregar_com(monkeypatch, gpu_transcreve=True, tem_cache=tem_cache)
    # com o modelo baixado, nem tenta o huggingface; sem ele, baixa normalmente
    assert servico.modelo.local_files_only is tem_cache
    assert len(criados) == 1
