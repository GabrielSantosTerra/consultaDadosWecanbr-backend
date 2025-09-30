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
    uuid: Optional[str] = None  # ➜ garantir que existe
    id_ged: Optional[str] = None  # ➜ garantir que existe

class StatusDocOut(BaseModel):
    id: int
    aceito: bool
    ip_usuario: str
    tipo_doc: str
    data: date
    hora: time
    cpf: Optional[str] = None
    matricula: Optional[str] = None
    unidade: Optional[str] = None
    competencia: Optional[str] = None
    uuid: Optional[str] = None
    id_ged: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class StatusDocOutWithFile(StatusDocOut):
    base64: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class StatusDocQuery(BaseModel):
    uuid: Optional[str] = None
    id: Optional[int] = None
    cpf: Optional[str] = None
    matricula: Optional[str] = None
    competencia: Optional[str] = None
    id_ged: Optional[str] = None