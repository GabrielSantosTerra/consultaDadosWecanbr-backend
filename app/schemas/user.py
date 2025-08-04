# app/schemas/user.py

from pydantic import BaseModel, ConfigDict, Field
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

class PessoaCreate(PessoaBase):
    pass

class PessoaRead(PessoaBase):
    id: int

#
# Schemas para Usuário
#
class UsuarioBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_pessoa: int
    nome: str
    cpf: Annotated[str, Field(min_length=11, max_length=14)]

class UsuarioCreate(UsuarioBase):
    senha: Annotated[str, Field(min_length=6)]

class UsuarioRead(UsuarioBase):
    id: int

#
# Wrappers para registro, login e respostas
#
class CadastroPessoa(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pessoa: PessoaCreate
    usuario: UsuarioCreate

class UsuarioLogin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    usuario: str   # pode ser e-mail ou CPF
    senha: str

class PessoaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nome: str
    cpf: Optional[str]
    cliente: Optional[str]
    centro_de_custo: Optional[str]
    matricula: Optional[str]
    gestor: Optional[bool]
    email: str     # do Usuario associado

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
