from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# aqui eh a "string de conexao". 
# depois a pessoa c vai te passar qual o usuario, senha e nome do banco certinho.
# por enquanto, deixamos um padrao local pra testar:
URL_DO_BANCO = "postgresql+psycopg://postgres:admin@localhost:5432/pizzariadb"

# o engine eh a peca q realmente vai la no postgre e conecta
engine = create_engine(URL_DO_BANCO)

# a session local eh oq a gnt vai usar em cada rota (pra abrir e fechar a conexao a cada pedido)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# o base eh a classe mae q a pessoa c vai usar pra criar os modelos (tabelas) dps
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