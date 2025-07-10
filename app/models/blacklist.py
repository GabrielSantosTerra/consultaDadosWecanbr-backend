from sqlalchemy import Column, String, DateTime
from app.database.connection import Base

class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"
    __table_args__ = {"schema": "app_rh"}  # ✅ define o schema correto

    jti = Column(String, primary_key=True, index=True)
    expira_em = Column(DateTime, nullable=False)
