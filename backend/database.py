from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import URL_DO_BANCO

# a "string de conexao" agora vem do config.py (variavel de ambiente DATABASE_URL)

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
