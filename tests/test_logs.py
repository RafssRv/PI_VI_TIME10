"""Dados da conversa não devem virar diagnóstico, nem dentro de exceções."""

import asyncio
import gc
import io
import json
import logging
import runpy
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import UploadFile
from sqlalchemy.exc import StatementError

import main
from rotas import voz
import repositorio
import turno_de_voz
from atendimento import Atendimento
from database import SessionLocal
from test_turno_de_voz import Tela
from test_websocket import executar, texto, audio, INICIO, FIM


CPF = "11122233396"
NOME = "Marina Privacidade"
TELEFONE = "19987654321"
ENDERECO = "Rua Privacidade, 987"
SEGREDOS = [CPF, "111.222.333-96", NOME, TELEFONE, "(19) 98765-4321", ENDERECO]
DADOS = " | ".join(SEGREDOS)


def conferir_logs(capsys, caplog):
    captura = capsys.readouterr()
    # Também verifica argumentos/traceback retidos no LogRecord antes de formatar.
    registros = caplog.text + repr([r.__dict__ for r in caplog.records])
    for segredo in SEGREDOS:
        assert segredo not in captura.out + captura.err + registros
    assert all(r.exc_info is None for r in caplog.records)


def erro_banco():
    return StatementError("falha " + DADOS, "INSERT INTO cliente VALUES (:dados)",
                          {"dados": DADOS}, RuntimeError(DADOS))


@pytest.fixture
def chamada_privada(db, monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    resposta = tmp_path / "resposta.wav"
    resposta.write_bytes(b"audio")
    fala = {"texto": ""}
    agente = {
        "salvar_fala_em_wav": lambda audio, inicio: ("cliente.wav", inicio + 1),
        "transcrever": lambda caminho: fala["texto"],
        "sintetizar_resposta": lambda texto: resposta,
    }
    monkeypatch.setattr(turno_de_voz, "carregar_agente", lambda: agente)
    atendimento = Atendimento(abrir_sessao=SessionLocal, conversar=lambda *a, **k: json.dumps({
        "resposta": "Confirmando " + DADOS, "itens": [{"produto": "Pizza Margherita",
        "quantidade": 1}], "endereco": ENDERECO, "fechar": True,
    }))
    tela = Tela()
    numero = 0

    def falar(texto):
        nonlocal numero
        numero += 1
        fala["texto"] = texto
        tela.eventos.clear()
        asyncio.run(turno_de_voz.atender_turno(
            tela, b"audio", numero - 1, numero, atendimento))
        return list(tela.eventos)

    return atendimento, falar, agente, resposta


def test_cadastro_e_pedido_preservam_dados_na_tela_mas_nao_nos_logs(
    chamada_privada, capsys, caplog,
):
    atendimento, falar, _, _ = chamada_privada
    for texto in [CPF, "sim", NOME, TELEFONE]:
        falar(texto)
    eventos = falar(ENDERECO)
    resumo = next(e["texto"] for e in eventos
                  if e["tipo"] == "transcricao" and e["quem"] == "atendente")
    assert NOME in resumo and ENDERECO in resumo and "(19) 98765-4321" in resumo
    falar("sim")
    falar("uma margherita no pix")
    eventos = falar("sim")
    assert any(e["tipo"] == "pedido_salvo" for e in eventos)
    pedido = next(e for e in eventos if e["tipo"] == "pedido")
    assert pedido["cliente"]["nome"] == NOME
    assert pedido["endereco_entrega"] == ENDERECO
    conferir_logs(capsys, caplog)
    assert "turno=8" in caplog.text and "etapa=" in caplog.text
    assert atendimento.id_chamada in caplog.text
    assert Atendimento().id_chamada != atendimento.id_chamada


@pytest.mark.parametrize("etapa", ["dependencias", "audio", "transcricao", "ollama", "piper"])
def test_erro_de_voz_nao_expoe_excecao_nos_logs_ou_no_evento(
    chamada_privada, monkeypatch, capsys, caplog, etapa,
):
    atendimento, falar, agente, _ = chamada_privada

    def falhar(*a, **k):
        if etapa == "dependencias":
            raise ImportError(DADOS, name=DADOS)
        raise RuntimeError(DADOS)

    if etapa == "dependencias":
        monkeypatch.setattr(turno_de_voz, "carregar_agente", falhar)
    elif etapa == "ollama":
        monkeypatch.setattr(atendimento, "responder_com_eventos", falhar)
    else:
        chave = {"audio": "salvar_fala_em_wav", "transcricao": "transcrever",
                 "piper": "sintetizar_resposta"}[etapa]
        agente[chave] = falhar

    eventos = falar(DADOS)
    erros = [e for e in eventos if e["tipo"] == "erro"]
    assert len(erros) == 1 and erros[0]["fatal"] is False
    assert eventos[-1] == {"tipo": "estado", "etapa": "ouvindo"}
    for segredo in SEGREDOS:
        assert segredo not in json.dumps(erros, ensure_ascii=False)
    conferir_logs(capsys, caplog)
    assert atendimento.id_chamada in caplog.text
    assert "turno=1" in caplog.text and "categoria=" in caplog.text


@pytest.mark.parametrize("operacao,validacao", [
    ("buscar_cliente_por_cpf", False), ("criar_cliente", False),
    ("criar_cliente", True), ("listar_cardapio", False),
    ("salvar_pedido", False), ("salvar_pedido", True),
])
def test_falhas_do_repositorio_nao_registram_parametros_pessoais(
    chamada_privada, cpf_da_ana, monkeypatch, capsys, caplog, operacao, validacao,
):
    atendimento, falar, _, _ = chamada_privada
    if operacao == "criar_cliente":
        for texto in [CPF, "sim", NOME, TELEFONE, ENDERECO]:
            falar(texto)
        entrada = "sim"
    elif operacao == "buscar_cliente_por_cpf":
        entrada = CPF
    else:
        falar(cpf_da_ana)
        entrada = "uma margherita no pix"
        if operacao == "salvar_pedido":
            falar(entrada)
            entrada = "sim"
    caplog.clear()
    capsys.readouterr()

    def falhar(*a, **k):
        raise ValueError(DADOS) if validacao else erro_banco()

    monkeypatch.setattr(repositorio, operacao, falhar)
    eventos = falar(entrada)
    assert not any(e["tipo"] == "pedido_salvo" for e in eventos)
    conferir_logs(capsys, caplog)
    avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(atendimento.id_chamada in r and "etapa=" in r and "categoria=" in r
               for r in avisos)


def test_cardapio_indisponivel_na_conversa_livre_nao_vaza_dados(
    chamada_privada, monkeypatch, capsys, caplog,
):
    atendimento, falar, _, _ = chamada_privada
    falar(CPF)
    falar("nao")
    caplog.clear()
    capsys.readouterr()

    def falhar(*a, **k):
        raise erro_banco()

    monkeypatch.setattr(repositorio, "listar_cardapio", falhar)
    eventos = falar("oi")
    assert any(e["tipo"] == "audio_resposta" for e in eventos)
    conferir_logs(capsys, caplog)
    assert "categoria=banco" in caplog.text


def test_json_invalido_do_modelo_nao_vaza_documento(
    chamada_privada, cpf_da_ana, monkeypatch, capsys, caplog,
):
    atendimento, falar, _, _ = chamada_privada
    falar(cpf_da_ana)
    monkeypatch.setattr(atendimento, "_conversar", lambda *a, **k: DADOS)
    falar("uma margherita")
    conferir_logs(capsys, caplog)
    assert "categoria=modelo_invalido" in caplog.text


@pytest.mark.parametrize("falha", [False, True])
def test_upload_nao_registra_nome_do_arquivo_ou_detalhe_da_falha(
    monkeypatch, tmp_path, capsys, caplog, falha,
):
    caplog.set_level(logging.INFO)
    monkeypatch.chdir(tmp_path)
    if falha:
        def falhar(*a, **k):
            raise OSError(DADOS)
        monkeypatch.setattr(voz.shutil, "copyfileobj", falhar)
    arquivo = UploadFile(io.BytesIO(b"audio"), filename=CPF + ".webm")
    resposta = asyncio.run(voz.processar_audio(arquivo))
    assert resposta.status_code == (500 if falha else 200)
    if falha:
        assert not any(s in resposta.body.decode() for s in SEGREDOS)
    conferir_logs(capsys, caplog)
    assert "etapa=upload" in caplog.text


def test_falha_inesperada_da_chamada_nao_escapa_para_traceback_do_servidor(
    executar, monkeypatch, capsys, caplog,
):
    async def falhar(*a, **k):
        raise erro_banco()

    monkeypatch.setattr(voz, "atender_turno", falhar)
    eventos, fechamentos = executar([texto(INICIO), audio(), texto(FIM)])
    assert fechamentos == [1011]
    assert eventos[-1]["tipo"] == "erro" and eventos[-1]["fatal"] is True
    assert not any(s in json.dumps(eventos, ensure_ascii=False) for s in SEGREDOS)
    conferir_logs(capsys, caplog)
    assert "categoria=inesperada" in caplog.text


def test_fluxo_legado_do_agente_nao_imprime_a_conversa(monkeypatch, capsys, caplog):
    for nome, funcao in [("llm_service", "responder"), ("whisper_service", "transcrever"),
                         ("piper_service", "sintetizar_resposta")]:
        modulo = ModuleType("services." + nome)
        setattr(modulo, funcao, lambda *a: DADOS)
        monkeypatch.setitem(sys.modules, modulo.__name__, modulo)
    caminho = Path(main.__file__).parent / "agente" / "main.py"
    agente = runpy.run_path(str(caminho))
    assert agente["processar_audio"]("audio.wav") == (DADOS, DADOS)
    conferir_logs(capsys, caplog)


@pytest.mark.parametrize("codigo", [0, 1])
def test_saida_do_processo_de_sintese_nao_vaza_texto(
    monkeypatch, tmp_path, capfd, caplog, codigo,
):
    from agente.services import piper_service

    monkeypatch.setattr(piper_service, "PASTA_AGENTE", tmp_path)
    popen = piper_service.subprocess.Popen

    def processo_simulado(comando, **kwargs):
        # Processo real que ecoa a fala nos dois canais, como um diagnóstico de falha.
        script = ("import sys; texto=sys.stdin.read(); print(texto); "
                  "print(texto,file=sys.stderr); sys.exit(" + str(codigo) + ")")
        return popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(piper_service.subprocess, "Popen", processo_simulado)
    if codigo:
        with pytest.raises(RuntimeError, match="codigo 1"):
            piper_service.sintetizar_resposta(DADOS)
    else:
        assert piper_service.sintetizar_resposta(DADOS).name == "resposta.wav"
    conferir_logs(capfd, caplog)


@pytest.mark.parametrize("cancelamento", [False, True])
def test_falha_tardia_apos_perder_conexao_nao_vaza_no_asyncio(monkeypatch, cancelamento):
    liberar = threading.Event()
    wait_for = asyncio.wait_for

    async def espera_curta(tarefa, timeout):
        return await wait_for(tarefa, timeout=0.01)

    monkeypatch.setattr(turno_de_voz.asyncio, "wait_for", espera_curta)

    class Conexao:
        envios = 0

        async def send_json(self, evento):
            self.envios += 1
            if self.envios == 2:
                if cancelamento:
                    raise asyncio.CancelledError()
                raise ConnectionError("conexao encerrada")

    def trabalho():
        liberar.wait(timeout=2)
        raise erro_banco()

    async def executar():
        loop = asyncio.get_running_loop()
        erros_nao_observados = []
        loop.set_exception_handler(lambda loop, contexto: erros_nao_observados.append(contexto))
        try:
            await turno_de_voz.rodar_sem_travar(Conexao(), 1, "pensando", trabalho)
        except (ConnectionError, asyncio.CancelledError):
            pass
        else:
            pytest.fail("o teste deveria perder a conexão durante o heartbeat")
        finally:
            liberar.set()
        # wait aguarda a conclusão sem consumir sua exceção; a produção deve fazer isso.
        pendentes = asyncio.all_tasks() - {asyncio.current_task()}
        await asyncio.wait(pendentes)
        pendentes.clear()
        gc.collect()
        await asyncio.sleep(0)
        assert erros_nao_observados == []

    asyncio.run(executar())
