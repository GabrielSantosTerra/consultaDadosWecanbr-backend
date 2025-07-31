from sqlalchemy import Column, Integer, String, Date, Time
from app.database.connection import Base

class Gravadas(Base):
    __tablename__ = "tb_gravadas"
    __table_args__ = {"schema": "app_rh"}

    id = Column(Integer, primary_key=True, index=True)
    registration_number = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)