from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List

from app.database.connection import get_db
from app.schemas.document import TipoDocumentoResponse
from app.models.document import TipoDocumento
from app.models.user import Pessoa
from app.utils.jwt_handler import verificar_token

router = APIRouter()

@router.get("/documents", response_model=List[TipoDocumentoResponse])
def listar_tipos_documentos(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Token de autenticação ausente")

    payload = verificar_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")

    documentos = db.query(TipoDocumento).all()
    return documentos
