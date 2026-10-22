from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# a string de conexao vem do config.py, que le a variavel de ambiente DATABASE_URL.
# nao cravar aqui: o default do config ja bate com o docker-compose e usa 127.0.0.1 em vez
# de localhost (no windows o localhost tenta ipv6 primeiro e cada conexao trava 30 segundos)
from config import URL_DO_BANCO

# o engine eh a peca q realmente vai la no postgre e conecta
engine = create_engine(URL_DO_BANCO)

# a session local eh oq a gnt vai usar em cada rota (pra abrir e fechar a conexao a cada pedido)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# o base eh a classe mae q os modelos (tabelas) do models.py herdam
Base = declarative_base()

def get_db():
    """
    funcao pra gente chamar nas rotas do fastapi.
    ela abre uma sessao com o banco e garante que vai fechar no final.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
