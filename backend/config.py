import os

# tudo q muda de maquina pra maquina fica aqui, lido do ambiente.
# pra definir as variaveis antes de subir o servidor:
#   windows (powershell): $env:CPF_HMAC_SECRET = "um-segredo-bem-grande"
#   linux / mac:          export CPF_HMAC_SECRET="um-segredo-bem-grande"

# o default tem q bater com o docker-compose.yml (usuario pizzaria / senha pizzaria123 / banco pizzaria)
URL_DO_BANCO = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://pizzaria:pizzaria123@localhost:5432/pizzaria",
)

_SEGREDO_DE_DESENVOLVIMENTO = "segredo-local-so-pra-desenvolvimento-nao-use-de-verdade"

# fora do ambiente de desenvolvimento (AMBIENTE=producao, homolog, oq for) o servidor nem sobe
# sem o segredo, pq o de baixo esta versionado no github: hmac com segredo publico eh a mesma
# coisa que sha256 puro, e cpf tem so ~10^9 combinacoes, quebra na forca bruta
AMBIENTE = os.getenv("AMBIENTE", "dev")

SEGREDO_CPF = os.getenv("CPF_HMAC_SECRET")

if not SEGREDO_CPF:
    if AMBIENTE != "dev":
        raise RuntimeError(
            "CPF_HMAC_SECRET nao esta definida e AMBIENTE={!r} nao eh 'dev'. "
            "defina a variavel antes de subir o servidor, e nao troque depois: "
            "mudar o segredo invalida TODOS os cpf_hash ja gravados no banco.".format(AMBIENTE)
        )
    SEGREDO_CPF = _SEGREDO_DE_DESENVOLVIMENTO
    # aviso sai uma vez so, no import do modulo
    print(
        "[config] ATENCAO: a variavel CPF_HMAC_SECRET nao esta definida, "
        "usando o segredo de desenvolvimento (que esta no repositorio). "
        "vale so pra maquina local; em qualquer outro lugar defina a variavel."
    )
