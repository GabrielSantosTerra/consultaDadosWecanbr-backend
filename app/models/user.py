from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from app.database.connection import Base

class Pessoa(Base):
    __tablename__ = "tb_pessoa"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    cpf = Column(String, unique=True, nullable=False)
    cliente = Column(String, nullable=False)
    centro_de_custo = Column(String, nullable=False)
    matricula = Column(String, nullable=False)
    gestor = Column(Boolean, nullable=False, default=False)

class Usuario(Base):
    __tablename__ = "tb_usuario"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    id_pessoa = Column(Integer, ForeignKey("app_rh.tb_pessoa.id"), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    senha = Column(String(255), nullable=False)