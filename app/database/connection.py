# app/database/connection.py

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Monta a URL de conexão com base nas variáveis de ambiente
DB_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@" \
         f"{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

# Cria o engine de conexão com o banco
engine = create_engine(DB_URL)

# Cria a fábrica de sessões para o SQLAlchemy
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para os modelos usarem como herança
Base = declarative_base()

# Função que retorna uma sessão de banco para ser usada como dependência no FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
