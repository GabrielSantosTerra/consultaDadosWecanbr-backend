from sqlalchemy import Column, Integer, String, ForeignKey
from app.database.connection import Base

class Pessoa(Base):
    __tablename__ = "tb_pessoa"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    cpf = Column(String(14), unique=True, index=True, nullable=False)
    cliente = Column(String(20), nullable=True)
    centro_de_custo = Column(String(200), nullable=True)
    matricula = Column(String(20), nullable=True)

class Usuario(Base):
    __tablename__ = "tb_usuario"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    id_pessoa = Column(Integer, ForeignKey("app_rh.tb_pessoa.id"), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    senha = Column(String(255), nullable=False)