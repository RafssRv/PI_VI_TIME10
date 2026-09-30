import hashlib
import hmac
import re

from config import SEGREDO_CPF


def normalizar_cpf(cpf):
    """
    o cpf chega da transcricao de voz cheio de ponto, traco, espaco e palavra solta.
    aqui a gente joga fora tudo q nao eh digito e devolve so os numeros.
    """
    if cpf is None:
        return ""
    return re.sub(r"\D", "", str(cpf))


def cpf_valido(cpf):
    """
    confere os dois digitos verificadores pelo algoritmo oficial.
    isso eh oq pega erro do whisper (trocou um 6 por 7) antes de bater no banco.
    """
    digitos = normalizar_cpf(cpf)

    if len(digitos) != 11:
        return False

    # 00000000000, 11111111111 e afins passam na conta do dv mas nao sao cpf de ninguem
    if digitos == digitos[0] * 11:
        return False

    # primeiro dv usa os 9 primeiros digitos, o segundo usa os 10 primeiros
    for quantidade in (9, 10):
        soma = 0
        peso = quantidade + 1
        for numero in digitos[:quantidade]:
            soma += int(numero) * peso
            peso -= 1
        resto = (soma * 10) % 11
        if resto == 10:
            resto = 0
        if resto != int(digitos[quantidade]):
            return False

    return True


def hashear_cpf(cpf):
    """
    devolve o hexdigest (64 chars) q vai no campo cliente.cpf_hash.
    levanta ValueError se o cpf nao prestar, entao quem chama trata e pede pro cliente repetir.
    """
    digitos = normalizar_cpf(cpf)

    if len(digitos) != 11:
        raise ValueError(
            "cpf precisa ter 11 digitos, vieram {}. peca pro cliente repetir.".format(len(digitos))
        )

    if not cpf_valido(digitos):
        raise ValueError("cpf invalido: os digitos verificadores nao batem. peca pro cliente repetir.")

    # hmac com segredo do servidor em vez de sha256 puro: cpf tem so ~10^9 combinacoes,
    # entao hash sem segredo qualquer um quebra por forca bruta em minutos
    return hmac.new(
        SEGREDO_CPF.encode("utf-8"),
        digitos.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
