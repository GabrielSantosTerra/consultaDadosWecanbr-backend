from sqlalchemy import Column, Integer, String, Boolean, BigInteger, Date, Time, Text, text
from sqlalchemy.dialects.postgresql import INET, BYTEA, UUID as PG_UUID
from app.database.connection import Base

class TipoDocumento(Base):
    __tablename__ = "tb_tipodocumento"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)


class StatusDocumento(Base):
    __tablename__ = "tb_status_doc"
    __table_args__ = {"schema": "app_rh"}

    id          = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    aceito      = Column(Boolean, nullable=False)
    ip_usuario  = Column(INET, nullable=False)
    tipo_doc    = Column(Text, nullable=False)
    data        = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    hora        = Column(Time, nullable=False, server_default=text("CURRENT_TIME"))
    cpf         = Column(Text, nullable=True)
    matricula   = Column(Text, nullable=True)
    unidade     = Column(Text, nullable=True)
    competencia = Column(Text, nullable=True)
    arquivo     = Column(BYTEA, nullable=True)
    uuid        = Column(PG_UUID(as_uuid=False), nullable=True, index=True)
    id_ged      = Column(Text, nullable=True, index=True)