from pydantic import BaseModel, constr, ConfigDict, StringConstraints, field_serializer
from typing import Optional, List, Pattern
from typing_extensions import Annotated
from datetime import date, time

class TipoDocumentoResponse(BaseModel):
    id: int
    nome: str

    model_config = ConfigDict(from_attributes=True)

class DeletarDocumentosRequest(BaseModel):
    id_template: int
    campo: Optional[str] = None
    valor: Optional[str] = None
    dt_criacao: Optional[str] = None

class DeletarDocumentosResponse(BaseModel):
    total_encontrados: int
    total_deletados: int
    falhas: List[dict]

NomeDoc = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

class StatusDocCreate(BaseModel):
    aceito: bool
    tipo_doc: str
    base64: str
    matricula: str
    cpf: str
    unidade: str
    competencia: str

class StatusDocOut(BaseModel):
    id: int
    aceito: bool
    ip_usuario: str
    tipo_doc: str
    data: date          # <<< agora é date
    hora: time          # <<< agora é time
    cpf: Optional[str] = None
    matricula: Optional[str] = None
    unidade: Optional[str] = None
    competencia: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)