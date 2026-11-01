"""Contrato de entrada do WebSocket de voz, versão 1."""

import json


VERSAO_PROTOCOLO = 1
LIMITE_CONTROLE_BYTES = 4 * 1024
LIMITE_BLOCO_AUDIO_BYTES = 1024 * 1024
LIMITE_AUDIO_CHAMADA_BYTES = 20 * 1024 * 1024
DURACAO_MAXIMA_CHAMADA_S = 15 * 60

FORMATOS_AUDIO = {
    "audio/webm", "audio/webm;codecs=opus",
    "audio/ogg", "audio/ogg;codecs=opus",
    "audio/mp4", "audio/mp4;codecs=mp4a.40.2",
}
CAMPOS = {
    "iniciar_chamada": {"tipo", "versao_protocolo", "formato_audio", "chunk_ms"},
    "fim_da_fala": {"tipo", "turno", "duracao_ms"},
    "resposta_tocada": {"tipo", "turno"},
    "timeout": {"tipo", "turno"},
    "encerrar_chamada": {"tipo", "motivo"},
}


class ErroProtocolo(ValueError):
    def __init__(self, mensagem, codigo=1008):
        super().__init__(mensagem)
        self.codigo = codigo


def _inteiro(dados, campo, minimo, maximo):
    valor = dados[campo]
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ErroProtocolo(f"O campo {campo} precisa ser um inteiro entre {minimo} e {maximo}.")


def validar_controle(texto):
    """Rejeita antes do processamento; mensagens de erro não repetem a entrada."""
    if len(texto.encode("utf-8")) > LIMITE_CONTROLE_BYTES:
        raise ErroProtocolo("A mensagem de controle ultrapassou o limite permitido.", 1009)
    try:
        dados = json.loads(texto)
    except (ValueError, RecursionError):
        raise ErroProtocolo("A mensagem de controle precisa ser um objeto JSON válido.") from None
    if not isinstance(dados, dict) or not isinstance(dados.get("tipo"), str):
        raise ErroProtocolo("A mensagem de controle precisa conter um tipo válido.")
    tipo = dados["tipo"]
    if tipo not in CAMPOS or set(dados) != CAMPOS[tipo]:
        raise ErroProtocolo("Tipo desconhecido ou campos incompatíveis com o protocolo.")

    if tipo == "iniciar_chamada":
        _inteiro(dados, "versao_protocolo", VERSAO_PROTOCOLO, VERSAO_PROTOCOLO)
        _inteiro(dados, "chunk_ms", 1, 10000)
        formato = dados["formato_audio"]
        if not isinstance(formato, str) or formato.lower().replace(" ", "") not in FORMATOS_AUDIO:
            raise ErroProtocolo("Formato de áudio não suportado pelo protocolo.")
    elif tipo in {"fim_da_fala", "resposta_tocada", "timeout"}:
        _inteiro(dados, "turno", 1, 2**31 - 1)
        if tipo == "fim_da_fala":
            _inteiro(dados, "duracao_ms", 1, DURACAO_MAXIMA_CHAMADA_S * 1000)
    else:
        motivo = dados["motivo"]
        if not isinstance(motivo, str) or not motivo.strip() or len(motivo) > 80:
            raise ErroProtocolo("O motivo do encerramento precisa ter entre 1 e 80 caracteres.")
    return dados
