# liga a tela de chamada no agente do rafael (pasta agente).
# cada vez q o cliente para de falar, a gente faz um "turno":
# fala -> texto (whisper) -> resposta (llama) -> voz (piper) -> manda pra tela tocar

import asyncio
import logging

logger = logging.getLogger(__name__)

# o agente so eh carregado na primeira fala, e nao quando o servidor liga.
# assim o servidor sobe rapido e funciona ate pra quem nao instalou o whisper/piper
_agente = None


def carregar_agente():
    global _agente
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


def _observar_conclusao(tarefa):
    # Evita o traceback automático do asyncio após perder a conexão, sem cancelar a gravação.
    if not tarefa.cancelled():
        tarefa.exception()


async def rodar_sem_travar(websocket, turno, etapa, funcao, *argumentos):
    """
    roda uma etapa pesada sem travar o servidor.
    enquanto ela roda, avisa a tela a cada 5 s q ainda ta trabalhando,
    pq a tela desiste se ficar 15 s sem resposta (e o llama pode demorar mais q isso)
    """
    await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})

    tarefa = asyncio.create_task(asyncio.to_thread(funcao, *argumentos))
    try:
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(tarefa), timeout=5)
            except asyncio.TimeoutError:
                await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})
    finally:
        tarefa.add_done_callback(_observar_conclusao)


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
    try:
        agente = carregar_agente()
    except ImportError:
        await mandar_erro(websocket, "transcricao",
                          "Faltam bibliotecas do agente no servidor. Rode o pip install.",
                          atendimento.id_chamada, turno, "dependencias")
        return amostra_inicio

    # 1. salva a fala do cliente em agente/audio/cliente.wav
    try:
        caminho_wav, amostra_fim = await rodar_sem_travar(
            websocket, turno, "transcrevendo",
            agente["salvar_fala_em_wav"], bytes(audio_da_chamada), amostra_inicio)
    except Exception:
        await mandar_erro(websocket, "audio", "Não consegui ler o áudio gravado.",
                          atendimento.id_chamada, turno, "decodificacao")
        return amostra_inicio

    # 2. whisper: transforma a fala em texto
    try:
        texto_cliente = await rodar_sem_travar(
            websocket, turno, "transcrevendo", agente["transcrever"], str(caminho_wav))
    except Exception:
        await mandar_erro(websocket, "transcricao", "A transcrição falhou.",
                          atendimento.id_chamada, turno, "transcricao")
        return amostra_fim

    texto_cliente = texto_cliente.strip()
    logger.info("chamada=%s turno=%s etapa=transcricao status=concluida",
                atendimento.id_chamada, turno)

    if not texto_cliente:
        await mandar_erro(websocket, "transcricao", "Não entendi. Pode repetir?",
                          atendimento.id_chamada, turno, "fala_vazia")
        return amostra_fim

    await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "cliente",
                               "texto": texto_cliente, "parcial": False})

    # 3. atendimento: identifica/cadastra o cliente e, depois disso, conversa pelo llama
    try:
        resultado = await rodar_sem_travar(
            websocket, turno, "pensando", atendimento.responder_com_eventos, texto_cliente)
    except Exception:
        await mandar_erro(websocket, "ollama",
                          "Não consegui concluir o atendimento. Pode tentar novamente?",
                          atendimento.id_chamada, turno, "atendimento")
        return amostra_fim

    # A gravação já terminou: a tela precisa saber mesmo se a síntese falhar depois.
    for evento in resultado["eventos"]:
        await websocket.send_json({**evento, "turno": turno})

    texto_resposta = resultado["texto"].strip()
    logger.info("chamada=%s turno=%s etapa=atendimento status=concluida",
                atendimento.id_chamada, turno)

    await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "atendente",
                               "texto": texto_resposta, "parcial": False})

    # 4. piper: transforma a resposta em voz (agente/audio/resposta.wav)
    try:
        caminho_resposta = await rodar_sem_travar(
            websocket, turno, "respondendo", agente["sintetizar_resposta"], texto_resposta)
    except Exception:
        await mandar_erro(websocket, "piper", "Não consegui gerar a voz da resposta.",
                          atendimento.id_chamada, turno, "sintese")
        return amostra_fim

    # 5. manda o audio pra tela: avisa q vai chegar, manda o arquivo e avisa q acabou
    await websocket.send_json({"tipo": "audio_resposta", "turno": turno, "formato": "audio/wav"})
    await websocket.send_bytes(caminho_resposta.read_bytes())
    await websocket.send_json({"tipo": "fim_audio"})

    return amostra_fim
