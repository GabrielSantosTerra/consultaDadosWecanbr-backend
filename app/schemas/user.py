from pydantic import BaseModel, EmailStr, Field

# Simples: nome, cpf, empresa
class PessoaBaseSimples(BaseModel):
    nome: str
    cpf: str = Field(..., min_length=11, max_length=14)
    cliente: str
    centro_de_custo: str
    matricula: str
    gestor: bool = False

class PessoaBaseColab(BaseModel):
    nome: str
    cpf: str = Field(..., min_length=11, max_length=14)
    cliente: str
    centro_de_custo: str
    matricula: str
    gestor: bool = False

class UsuarioBase(BaseModel):
    email: EmailStr
    senha: str

class CadastroPessoa(BaseModel):
    pessoa: PessoaBaseSimples
    usuario: UsuarioBase

class CadastroColaborador(BaseModel):
    pessoa: PessoaBaseColab
    usuario: UsuarioBase

class UsuarioLogin(BaseModel):
    usuario: str
    senha: str

class PessoaResponse(BaseModel):
    nome: str
    cpf: str
    email: EmailStr
    cliente: str
    centro_de_custo: str
    matricula: str
    gestor: bool

class ColabResponse(BaseModel):
    nome: str
    cpf: str
    centro_de_custo: str
    matricula: str
    cliente: str
    email: EmailStr
