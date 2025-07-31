from fastapi import FastAPI, Depends, HTTPException, APIRouter
from sqlalchemy.orm import Session
from datetime import datetime
from app.database.connection import SessionLocal, engine, Base
from app.models.gravadas import Gravadas as GravadaModel
from app.schemas.gravadas import GravadasCreate, Gravadas as GravadasSchema

# Cria a tabela tb_gravadas se não existir
Base.metadata.create_all(bind=engine)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/gravadas", response_model=GravadasSchema)
def create_gravada(gravada: GravadasCreate, db: Session = Depends(get_db)):
    """
    Recebe JSON conforme GravadasCreate e persiste na tabela tb_gravadas.
    Campos armazenados: registration_number, date, time.
    """
    # Conversão de data string para date
    if isinstance(gravada.date, str):
        date_obj = datetime.strptime(gravada.date, "%Y-%m-%d").date()
    else:
        date_obj = gravada.date

    # Conversão de hora string para time
    if isinstance(gravada.time, str):
        time_obj = datetime.strptime(gravada.time, "%H:%M").time()
    else:
        time_obj = gravada.time

    # Cria instância do model
    db_obj = GravadaModel(
        registration_number=gravada.employee.registration_number,
        date=date_obj,
        time=time_obj
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj
