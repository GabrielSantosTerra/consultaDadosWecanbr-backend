# app/routers/usuario.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database.connection import SessionLocal
from app.models.user import Usuario, Pessoa
from app.schemas.user import CadastroPessoa, UsuarioLogin, PessoaResponse

router = APIRouter(prefix="/user", tags=["Usuário"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/register", response_model=PessoaResponse)
def registrar_usuario(payload: CadastroPessoa, db: Session = Depends(get_db)):
    # Verifica se email já existe
    if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    # ✅ Corrigido aqui — usa o model Pessoa para a tabela tb_pessoa
    pessoa = Pessoa(**payload.pessoa.dict())
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)

    # ✅ Criação correta da credencial
    usuario = Usuario(
        id_pessoa=pessoa.id,
        email=payload.usuario.email,
        senha=payload.usuario.senha
    )
    db.add(usuario)
    db.commit()

    return pessoa

@router.post("/login", response_model=PessoaResponse)
def login(payload: UsuarioLogin, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == payload.email).first()
    if not usuario or usuario.senha != payload.senha:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    pessoa = db.query(Pessoa).filter(Pessoa.id == usuario.id_pessoa).first()
    return pessoa
