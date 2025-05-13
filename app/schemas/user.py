from pydantic import BaseModel, Field, EmailStr

class PessoaBase(BaseModel):
    nome: str
    empresa: int
    cliente: int
    cpf: str = Field(..., min_length=11, max_length=14)

class PessoaResponse(PessoaBase):
    id: int
    class Config:
        orm_mode = True

class UsuarioBase(BaseModel):
    email: EmailStr
    senha: str

# Cadastro combinado
class CadastroPessoa(BaseModel):
    pessoa: PessoaBase
    usuario: UsuarioBase

# Login
class UsuarioLogin(BaseModel):
    email: EmailStr
    senha: str
