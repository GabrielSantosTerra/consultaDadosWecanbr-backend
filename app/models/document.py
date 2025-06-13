from sqlalchemy import Column, Integer, String
from app.database.connection import Base

class TipoDocumento(Base):
    __tablename__ = "tb_tipodocumento"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
