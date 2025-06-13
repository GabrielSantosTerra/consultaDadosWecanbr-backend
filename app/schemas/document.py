from pydantic import BaseModel

class TipoDocumentoResponse(BaseModel):
    id: int
    nome: str

    class Config:
        orm_mode = True
