# liga a tela de chamada no agente do rafael (pasta agente).
# cada vez q o cliente para de falar, a gente faz um "turno":
# fala -> texto (whisper) -> resposta (llama) -> voz (piper) -> manda pra tela tocar

import asyncio
import hashlib
import logging
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from monitor import monitor

logger = logging.getLogger(__name__)

# o agente so eh carregado na primeira fala, e nao quando o servidor liga.
# assim o servidor sobe rapido e funciona ate pra quem nao instalou o whisper/piper
_agente = None
# a saudacao so muda com o periodo do dia, entao a voz eh gerada uma vez e reaproveitada
_saudacoes = {}
# o aquecimento roda em paralelo com a chamada: a trava evita carregar o whisper duas vezes
_trava_do_agente = threading.Lock()
_aquecimentos = set()


def carregar_agente():
    global _agente
    with _trava_do_agente:
        if _agente is None:
            from agente.services.audio_service import salvar_fala_em_wav
            from agente.services.whisper_service import transcrever
            from agente.services.piper_service import sintetizar_resposta

            # a resposta nao sai mais direto do llama: quem decide eh o atendimento.py
            _agente = {
                "salvar_fala_em_wav": salvar_fala_em_wav,
                "transcrever": transcrever,
                "sintetizar_resposta": sintetizar_resposta,
            }
    return _agente


def _aquecer_agente():
    try:
        carregar_agente()
    except Exception:
        # o primeiro turno tenta de novo e mostra o erro na tela
        logger.warning("etapa=aquecer_agente categoria=carregamento")


def aquecer_durante_a_saudacao():
    # o whisper leva segundos pra carregar: assim a primeira fala do cliente nao paga por isso
    tarefa = asyncio.create_task(asyncio.to_thread(_aquecer_agente))
    _aquecimentos.add(tarefa)
    tarefa.add_done_callback(_aquecimentos.discard)


def _observar_conclusao(tarefa):
    # Evita o traceback automático do asyncio após perder a conexão, sem cancelar a gravação.
    if not tarefa.cancelled():
        tarefa.exception()


async def _executar_guardando_erro(funcao, *argumentos):
    # no python 3.14 o shield avisa o loop de toda excecao que chega depois da conexao cair,
    # e esse aviso traz a mensagem do erro, que pode ter dado pessoal. por isso ela volta como valor
    try:
        return True, await asyncio.to_thread(funcao, *argumentos)
    except Exception as erro:
        return False, erro


async def rodar_sem_travar(websocket, turno, etapa, funcao, *argumentos):
    """
    roda uma etapa pesada sem travar o servidor.
    enquanto ela roda, avisa a tela a cada 5 s q ainda ta trabalhando,
    pq a tela desiste se ficar 15 s sem resposta (e o llama pode demorar mais q isso)
    """
    await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})

    tarefa = asyncio.create_task(_executar_guardando_erro(funcao, *argumentos))
    try:
        while True:
            try:
                sucesso, resultado = await asyncio.wait_for(asyncio.shield(tarefa), timeout=5)
                if sucesso:
                    return resultado
                raise resultado
            except asyncio.TimeoutError:
                await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})
    finally:
        tarefa.add_done_callback(_observar_conclusao)


async def saudar(websocket, atendimento):
    """o atendente fala primeiro. se a voz falhar, o texto ja esta na tela e a chamada segue."""
    texto = atendimento.saudacao()
    monitor.registrar_transcricao(atendimento.id_chamada, "atendente", texto, 0)
    await websocket.send_json({"tipo": "transcricao", "turno": 0, "quem": "atendente",
                               "texto": texto, "parcial": False})
    audio = _saudacoes.get(texto)
    if audio is None:
        try:
            # so o piper: carregar_agente tambem carregaria o whisper e atrasaria o inicio da chamada
            from agente.services.piper_service import sintetizar_resposta
            with TemporaryDirectory(prefix="pizzaria-saudacao-") as pasta:
                caminho = await asyncio.to_thread(sintetizar_resposta, texto, Path(pasta) / "saudacao.wav")
                audio = caminho.read_bytes()
        except Exception:
            logger.warning("chamada=%s etapa=saudacao categoria=sintese", atendimento.id_chamada)
            # a tela espera a saudacao de microfone fechado: sem audio, avisa que ja pode ouvir
            await websocket.send_json({"tipo": "estado", "etapa": "ouvindo"})
            aquecer_durante_a_saudacao()
            return
        _saudacoes[texto] = audio
    await websocket.send_json({"tipo": "audio_resposta", "turno": 0, "formato": "audio/wav"})
    await websocket.send_bytes(audio)
    await websocket.send_json({"tipo": "fim_audio", "turno": 0})
    aquecer_durante_a_saudacao()


async def mandar_erro(websocket, onde, mensagem, chamada_id, turno, categoria):
    # mostra um aviso na tela e libera o microfone de novo, sem derrubar a chamada
    logger.warning("chamada=%s turno=%s etapa=%s categoria=%s",
                   chamada_id, turno, onde, categoria)
    await websocket.send_json({"tipo": "erro", "onde": onde, "mensagem": mensagem, "fatal": False})
    await websocket.send_json({"tipo": "estado", "etapa": "ouvindo"})


async def atender_turno(websocket, audio_da_chamada, amostra_inicio, turno, atendimento):
    """
    faz um turno inteiro da conversa.
    atendimento eh o roteiro dessa chamada (atendimento.py), q lembra em q etapa ela ta.
    devolve onde essa fala terminou, pro proximo turno comecar dali
    """
    atendimento.turno_voz = turno
    # Cada turno tem seus proprios arquivos, inclusive em chamadas simultaneas.
    with TemporaryDirectory(prefix="pizzaria-turno-") as pasta:
        return await _atender_turno(
            websocket, audio_da_chamada, amostra_inicio, turno, atendimento, Path(pasta))


async def _atender_turno(websocket, audio_da_chamada, amostra_inicio, turno, atendimento, pasta):
    inicio_turno_global = time.perf_counter()
    metricas = {"turno": turno}
    try:
        agente = carregar_agente()
    except ImportError:
        await mandar_erro(websocket, "transcricao",
                          "Faltam bibliotecas do agente no servidor. Rode o pip install.",
                          atendimento.id_chamada, turno, "dependencias")
        return amostra_inicio

    # 1. salva a fala do cliente no diretorio exclusivo deste turno.
    monitor.atualizar_etapa(atendimento.id_chamada, "transcrevendo", turno)
    t0 = time.perf_counter()
    try:
        caminho_wav, amostra_fim = await rodar_sem_travar(
            websocket, turno, "transcrevendo",
            agente["salvar_fala_em_wav"], bytes(audio_da_chamada), amostra_inicio, pasta / "cliente.wav")
    except Exception:
        await mandar_erro(websocket, "audio", "Não consegui ler o áudio gravado.",
                          atendimento.id_chamada, turno, "decodificacao")
        return amostra_inicio

    # 2. whisper: transforma a fala em texto
    try:
        texto_cliente = await rodar_sem_travar(
            websocket, turno, "transcrevendo",
            lambda: agente["transcrever"](str(caminho_wav), atendimento.dica_de_transcricao()))
    except Exception:
        await mandar_erro(websocket, "transcricao", "A transcrição falhou.",
                          atendimento.id_chamada, turno, "transcricao")
        return amostra_fim

    metricas["whisper_ms"] = round((time.perf_counter() - t0) * 1000)
    texto_cliente = texto_cliente.strip()
    logger.info("chamada=%s turno=%s etapa=transcricao status=concluida",
                atendimento.id_chamada, turno)

    if not texto_cliente:
        resultado = {"texto": atendimento._esclarecer(
            atendimento._pendencia or "Não consegui ouvir palavras nessa fala. Pode falar mais perto do microfone?"),
            "eventos": []}
    else:
        # o painel do admin tambem fica aberto numa tela: recebe a mesma legenda, sem o cpf
        texto_na_tela = atendimento.texto_para_tela(texto_cliente)
        monitor.registrar_transcricao(atendimento.id_chamada, "cliente", texto_na_tela, turno)
        await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "cliente",
                                   "texto": texto_na_tela, "parcial": False})
        # 3. atendimento: identifica/cadastra o cliente e depois interpreta o pedido.
        monitor.atualizar_etapa(atendimento.id_chamada, "pensando", turno)
        t_llm = time.perf_counter()
        try:
            resultado = await rodar_sem_travar(
                websocket, turno, "pensando", atendimento.responder_com_eventos, texto_cliente)
        except Exception:
            await mandar_erro(websocket, "ollama",
                              "Não consegui concluir o atendimento. Pode tentar novamente?",
                              atendimento.id_chamada, turno, "atendimento")
            return amostra_fim
        metricas["llm_ms"] = round((time.perf_counter() - t_llm) * 1000)
        if getattr(atendimento, "ultimo_rastro", None) is not None:
            atendimento.ultimo_rastro["audio_cliente_sha256"] = hashlib.sha256(caminho_wav.read_bytes()).hexdigest()

    # A gravação já terminou: a tela precisa saber mesmo se a síntese falhar depois.
    for evento in resultado["eventos"]:
        await websocket.send_json({**evento, "turno": turno})
        if evento.get("tipo") in ("pedido", "pedido_salvo"):
            monitor.atualizar_comanda(atendimento.id_chamada, evento)

    texto_resposta = resultado["texto"].strip()
    logger.info("chamada=%s turno=%s etapa=atendimento status=concluida",
                atendimento.id_chamada, turno)

    monitor.registrar_transcricao(atendimento.id_chamada, "atendente", texto_resposta, turno)
    await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "atendente",
                               "texto": texto_resposta, "parcial": False})

    # 4. piper: gera a voz no mesmo diretorio exclusivo.
    monitor.atualizar_etapa(atendimento.id_chamada, "respondendo", turno)
    t_tts = time.perf_counter()
    try:
        caminho_resposta = await rodar_sem_travar(
            websocket, turno, "respondendo", agente["sintetizar_resposta"], texto_resposta,
            pasta / "resposta.wav")
    except Exception:
        await mandar_erro(websocket, "piper", "Não consegui gerar a voz da resposta.",
                          atendimento.id_chamada, turno, "sintese")
        return amostra_fim

    metricas["piper_ms"] = round((time.perf_counter() - t_tts) * 1000)
    metricas["total_ms"] = round((time.perf_counter() - inicio_turno_global) * 1000)
    monitor.registrar_metricas(atendimento.id_chamada, turno, metricas)

    # 5. manda o audio pra tela: avisa q vai chegar, manda o arquivo e avisa q acabou
    await websocket.send_json({"tipo": "audio_resposta", "turno": turno, "formato": "audio/wav"})
    audio_resposta = caminho_resposta.read_bytes()
    if getattr(atendimento, "ultimo_rastro", None) is not None and texto_cliente:
        atendimento.ultimo_rastro["audio_resposta_sha256"] = hashlib.sha256(audio_resposta).hexdigest()
    await websocket.send_bytes(audio_resposta)
    await websocket.send_json({"tipo": "fim_audio", "turno": turno})

    monitor.atualizar_etapa(atendimento.id_chamada, "ouvindo", turno)
    return amostra_fim
