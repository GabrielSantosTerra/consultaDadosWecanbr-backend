from pydantic import BaseModel, EmailStr, Field

class PessoaBase(BaseModel):
    nome: str
    cpf: str = Field(..., min_length=11, max_length=14)
    empresa: int
    cliente: int

class UsuarioBase(BaseModel):
    email: EmailStr
    senha: str

class CadastroPessoa(BaseModel):
    pessoa: PessoaBase
    usuario: UsuarioBase

class UsuarioLogin(BaseModel):
    usuario: str  # email ou cpf
    senha: str
class PessoaResponse(BaseModel):
    nome: str
    cpf: str
    empresa: int
    cliente: int
    email: EmailStr
