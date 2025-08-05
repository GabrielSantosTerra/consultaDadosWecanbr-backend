# app/schemas/user.py

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, Annotated
from datetime import date

#
# Schemas para Pessoa
#
class PessoaBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    centro_de_custo: Optional[str]
    cliente: Optional[str]
    cpf: Optional[Annotated[str, Field(min_length=11, max_length=14)]]
    matricula: Optional[str]
    data_nascimento: Optional[date]
    gestor: Optional[bool]

class PessoaCreate(BaseModel):
    nome: str
    cpf: str
    cliente: str
    centro_de_custo: str
    matricula: str
    gestor: bool
    data_nascimento: date

class PessoaRead(PessoaBase):
    id: int

#
# Schemas para Usuário
#
class UsuarioCreate(BaseModel):
    email: EmailStr
    senha: str

class UsuarioRead(BaseModel):
    id: int
    email: EmailStr
    id_pessoa: int
#
class CadastroPessoa(BaseModel):
    pessoa: PessoaCreate
    usuario: "UsuarioCreate"

class UsuarioLogin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    usuario: str   # e-mail ou CPF
    senha: str
class PessoaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    cpf: Optional[str]
    cliente: Optional[str]
    centro_de_custo: Optional[str]
    matricula: Optional[str]
    gestor: Optional[bool]
    email: str     # do Usuário associado

class CadastroColaborador(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pessoa: PessoaCreate
    usuario: UsuarioCreate

class ColabResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    cpf: Optional[str]
    cliente: Optional[str]
    centro_de_custo: Optional[str]
    matricula: Optional[str]
    email: str