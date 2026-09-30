"""
preparacao dos testes.

os testes NAO rodam no banco de desenvolvimento: eles criam um banco separado chamado
pizzaria_teste, dentro do mesmo container do postgres, e recriam o esquema do zero a cada
execucao. assim rodar a suite nunca apaga o que voce tem no banco do dia a dia.

o que voce precisa antes: o container de pe (npm run banco).
"""

import os
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"

# o backend importa pelo nome (config, models, repositorio), entao a pasta entra no caminho
sys.path.insert(0, str(BACKEND))

BANCO_DE_TESTE = "pizzaria_teste"

# segredo fixo: o hash do cpf precisa ser o mesmo em toda execucao, senao o cliente que o
# seed gravou nao e encontrado pela busca
os.environ.setdefault("CPF_HMAC_SECRET", "segredo-fixo-dos-testes-nao-use-em-producao")

_URL_DEV = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://pizzaria:pizzaria123@127.0.0.1:5432/pizzaria"
)
# aponta a aplicacao para o banco de teste ANTES de qualquer import do backend,
# porque o config.py le a variavel na hora em que e importado
os.environ["DATABASE_URL"] = _URL_DEV.rsplit("/", 1)[0] + "/" + BANCO_DE_TESTE


def _dsn(nome_do_banco):
    """monta o dsn puro do psycopg (sem o +psycopg do sqlalchemy)."""
    base = _URL_DEV.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0]
    return base + "/" + nome_do_banco


def _preparar_banco_de_teste():
    import psycopg

    try:
        conexao = psycopg.connect(_dsn("pizzaria"), autocommit=True, connect_timeout=5)
    except Exception as erro:
        pytest.exit(
            "nao consegui falar com o postgres ({}).\n"
            "suba o banco antes de rodar os testes:  npm run banco".format(erro),
            returncode=1,
        )

    with conexao:
        existe = conexao.execute(
            "select 1 from pg_database where datname = %s", (BANCO_DE_TESTE,)
        ).fetchone()
        if not existe:
            conexao.execute('create database "{}"'.format(BANCO_DE_TESTE))

    # esquema do zero a cada execucao: o banco.sql e a unica fonte da verdade
    with psycopg.connect(_dsn(BANCO_DE_TESTE), autocommit=True) as conexao:
        conexao.execute("drop schema public cascade")
        conexao.execute("create schema public")
        conexao.execute((RAIZ / "banco.sql").read_text(encoding="utf-8"))


@pytest.fixture(scope="session", autouse=True)
def banco_de_teste():
    """
    cria o banco, o esquema e popula UMA vez por execucao da suite.
    devolve a marca d'agua: o maior id de pedido e de cliente que o seed criou. tudo acima
    disso foi um teste que gravou, e e apagado no fim dele.
    (repovoar a cada teste deixava a suite em quatro minutos e meio; assim fica em segundos.)
    """
    _preparar_banco_de_teste()

    import seed
    from database import SessionLocal
    from models import Cliente, Pedido

    sessao = SessionLocal()
    try:
        seed.limpar_banco(sessao)
        produtos = seed.inserir_produtos(sessao)
        clientes = seed.inserir_clientes(sessao)
        seed.inserir_pedidos(sessao, clientes, produtos)
        sessao.commit()
        marca = {
            "pedido": sessao.query(Pedido).count() and max(p.id for p in sessao.query(Pedido)),
            "cliente": max(c.id for c in sessao.query(Cliente)),
        }
        return marca
    finally:
        sessao.close()


@pytest.fixture
def db(banco_de_teste):
    """
    uma sessao com o banco ja populado, igual ao que o seed cria.
    no fim do teste, o que ele gravou e apagado, entao um teste nunca ve o pedido do outro.
    """
    from database import SessionLocal
    from models import Cliente, ItemPedido, Pedido

    sessao = SessionLocal()
    try:
        yield sessao
    finally:
        sessao.rollback()
        # ordem das fks: item, pedido, cliente
        novos = [p.id for p in sessao.query(Pedido).filter(Pedido.id > banco_de_teste["pedido"])]
        if novos:
            sessao.query(ItemPedido).filter(ItemPedido.pedido_id.in_(novos)).delete(
                synchronize_session=False
            )
            sessao.query(Pedido).filter(Pedido.id.in_(novos)).delete(synchronize_session=False)
        sessao.query(Cliente).filter(Cliente.id > banco_de_teste["cliente"]).delete(
            synchronize_session=False
        )
        sessao.commit()
        sessao.close()


@pytest.fixture
def cpf_da_ana():
    """cpf do primeiro cliente do seed, com os digitos verificadores certos."""
    import seed

    return seed.gerar_cpf(seed.CLIENTES[0][3])


@pytest.fixture
def ana(db, cpf_da_ana):
    """o cliente que mais tem historico no seed, usado nos testes de recomendacao."""
    import repositorio

    return repositorio.buscar_cliente_por_cpf(db, cpf_da_ana)
