from pydantic import BaseModel

class TipoDocumentoResponse(BaseModel):
    id: int
    nome: str
    tipodoc: str

    class Config:
        orm_mode = True
