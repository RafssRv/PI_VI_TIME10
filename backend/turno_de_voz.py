# ponte entre a tela de chamada e o agente do rafael (pasta agente).
#
# um "turno" eh: o cliente fala -> a tela percebe o silencio e manda "fim_da_fala" ->
# a gente transforma a fala em texto, gera a resposta, transforma em voz e manda de volta.
#
# as mensagens que vao pra tela seguem o protocolo que esta descrito no comeco do
# frontend/app.js (estado, transcricao, audio_resposta, fim_audio, erro).

import asyncio

# o whisper e o piper so sao carregados na primeira fala, e nao quando o servidor sobe.
# assim o servidor continua ligando mesmo em quem ainda nao instalou essas bibliotecas
_agente = None


def carregar_agente():
    global _agente
    if _agente is None:
        from agente.services.audio_service import salvar_fala_em_wav
        from agente.services.whisper_service import transcrever
        from agente.services.llm_service import responder
        from agente.services.piper_service import sintetizar_resposta

        _agente = {
            "salvar_fala_em_wav": salvar_fala_em_wav,
            "transcrever": transcrever,
            "responder": responder,
            "sintetizar_resposta": sintetizar_resposta,
        }
    return _agente


async def rodar_sem_travar(websocket, turno, etapa, funcao, *argumentos):
    """
    roda uma etapa pesada (whisper, llama, piper) numa thread separada, pra nao travar o
    servidor. enquanto ela roda, a cada 5 s a gente avisa a tela que continua trabalhando:
    a tela desiste sozinha se ficar 15 s sem noticia, e o llama no cpu pode passar disso.
    """
    await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})

    tarefa = asyncio.create_task(asyncio.to_thread(funcao, *argumentos))
    while True:
        try:
            return await asyncio.wait_for(asyncio.shield(tarefa), timeout=5)
        except asyncio.TimeoutError:
            await websocket.send_json({"tipo": "estado", "etapa": etapa, "turno": turno})


async def mandar_erro(websocket, onde, mensagem):
    # erro nao fatal: aparece uma tarja na tela e o microfone volta a ouvir
    print(f"[turno] erro em {onde}: {mensagem}")
    await websocket.send_json({"tipo": "erro", "onde": onde, "mensagem": mensagem, "fatal": False})
    await websocket.send_json({"tipo": "estado", "etapa": "ouvindo"})


async def atender_turno(websocket, audio_da_chamada, amostra_inicio, turno):
    """
    faz um turno completo da conversa.
    devolve onde a fala terminou, pra o proximo turno nao repetir o mesmo audio.
    """
    try:
        agente = carregar_agente()
    except ImportError as erro:
        await mandar_erro(websocket, "transcricao",
                          f"Faltam bibliotecas do agente no servidor ({erro.name}). Rode o pip install.")
        return amostra_inicio

    # 1. salva a fala do cliente em agente/audio/cliente.wav
    try:
        caminho_wav, amostra_fim = await rodar_sem_travar(
            websocket, turno, "transcrevendo",
            agente["salvar_fala_em_wav"], bytes(audio_da_chamada), amostra_inicio)
    except Exception as erro:
        await mandar_erro(websocket, "audio", f"Não consegui ler o áudio gravado ({erro}).")
        return amostra_inicio

    # 2. whisper: fala -> texto
    try:
        texto_cliente = await rodar_sem_travar(
            websocket, turno, "transcrevendo", agente["transcrever"], str(caminho_wav))
    except Exception as erro:
        await mandar_erro(websocket, "transcricao", f"A transcrição falhou ({erro}).")
        return amostra_fim

    texto_cliente = texto_cliente.strip()
    print(f"[turno {turno}] cliente: {texto_cliente!r}")

    if not texto_cliente:
        await mandar_erro(websocket, "transcricao", "Não entendi. Pode repetir?")
        return amostra_fim

    await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "cliente",
                               "texto": texto_cliente, "parcial": False})

    # 3. llama: texto do cliente -> resposta do atendente
    try:
        texto_resposta = await rodar_sem_travar(
            websocket, turno, "pensando", agente["responder"], texto_cliente)
    except Exception as erro:
        await mandar_erro(websocket, "ollama",
                          f"Não consegui falar com o Ollama. Ele está aberto? ({erro.__class__.__name__})")
        return amostra_fim

    texto_resposta = texto_resposta.strip()
    print(f"[turno {turno}] atendente: {texto_resposta!r}")

    await websocket.send_json({"tipo": "transcricao", "turno": turno, "quem": "atendente",
                               "texto": texto_resposta, "parcial": False})

    # 4. piper: resposta em texto -> agente/audio/resposta.wav
    try:
        caminho_resposta = await rodar_sem_travar(
            websocket, turno, "respondendo", agente["sintetizar_resposta"], texto_resposta)
    except Exception as erro:
        await mandar_erro(websocket, "piper", f"Não consegui gerar a voz da resposta ({erro}).")
        return amostra_fim

    # 5. manda o wav pra tela: primeiro o aviso, depois os bytes, depois o fim
    await websocket.send_json({"tipo": "audio_resposta", "turno": turno, "formato": "audio/wav"})
    await websocket.send_bytes(caminho_resposta.read_bytes())
    await websocket.send_json({"tipo": "fim_audio"})

    return amostra_fim
