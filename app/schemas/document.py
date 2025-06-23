from pydantic import BaseModel
from typing import Optional, List

class TipoDocumentoResponse(BaseModel):
    id: int
    nome: str

    class Config:
        orm_mode = True

class DeletarDocumentosRequest(BaseModel):
    id_template: int
    campo: Optional[str] = None
    valor: Optional[str] = None
    dt_criacao: Optional[str] = None

class DeletarDocumentosResponse(BaseModel):
    total_encontrados: int
    total_deletados: int
    falhas: List[dict]