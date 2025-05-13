# app/routers/usuario.py
from fastapi import APIRouter, Depends, HTTPException, Request
from app.utils.jwt_handler import criar_token, verificar_token
from fastapi.responses import JSONResponse
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

@router.post("/login")
def login(payload: UsuarioLogin, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == payload.email).first()
    if not usuario or usuario.senha != payload.senha:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    pessoa = db.query(Pessoa).filter(Pessoa.id == usuario.id_pessoa).first()

    # authToken → dados da pessoa
    auth_token = criar_token({
        "id": pessoa.id,
        "nome": pessoa.nome,
        "cpf": pessoa.cpf
    }, expires_in=2)

    # loggedUser → apenas true
    logged_user = criar_token({
        "logged": True
    }, expires_in=2)

    # refreshToken → usado para renovar os dois acima
    refresh_token = criar_token({
        "id": pessoa.id,
        "tipo": "refresh"
    }, expires_in=10)

    return JSONResponse(content={
        "authToken": auth_token,
        "loggedUser": logged_user,
        "refreshToken": refresh_token
    })

@router.post("/refresh")
async def refresh_token(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    token = body.get("refreshToken")

    if not token:
        raise HTTPException(status_code=400, detail="refreshToken não fornecido")

    payload = verificar_token(token)

    if not payload or payload.get("tipo") != "refresh":
        raise HTTPException(status_code=401, detail="refreshToken inválido ou expirado")

    id_pessoa = payload.get("id")
    pessoa = db.query(Pessoa).filter(Pessoa.id == id_pessoa).first()

    if not pessoa:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Novo authToken e loggedUser
    novo_auth_token = criar_token({
        "id": pessoa.id,
        "nome": pessoa.nome,
        "cpf": pessoa.cpf
    }, expires_in=2)

    novo_logged_user = criar_token({
        "logged": True
    }, expires_in=2)

    return {
        "authToken": novo_auth_token,
        "loggedUser": novo_logged_user
    }