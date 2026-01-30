from sqlalchemy import Column, BigInteger, Integer, String, Boolean, Date, Time, ForeignKey, text
from app.database.connection import Base


class TokenInterno(Base):
    __tablename__ = "tb_token_interno"
    __table_args__ = {"schema": "app_rh"}

    id = Column(BigInteger, primary_key=True, index=True)

    id_pessoa = Column(Integer, ForeignKey("app_rh.tb_pessoa.id", ondelete="CASCADE"), nullable=False)

    token = Column(String(128), nullable=False, unique=True)  # hash do token

    data_criacao = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    hora_criacao = Column(Time, nullable=False, server_default=text("CURRENT_TIME"))

    tempo_expiracao_min = Column(Integer, nullable=False, server_default=text("15"))

    inativo = Column(Boolean, nullable=False, server_default=text("false"))
