from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import timedelta

from app.database.connection import get_db
from app.models.user import Usuario, Pessoa
from app.schemas.user import CadastroPessoa, UsuarioLogin, PessoaResponse
from app.utils.jwt_handler import criar_token, verificar_token

router = APIRouter()

@router.post("/user/register", response_model=PessoaResponse)
def registrar_usuario(payload: CadastroPessoa, db: Session = Depends(get_db)):
    if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    pessoa = Pessoa(**payload.pessoa.dict())
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)

    usuario = Usuario(
        id_pessoa=pessoa.id,
        email=payload.usuario.email,
        senha=payload.usuario.senha
    )
    db.add(usuario)
    db.commit()

    return PessoaResponse(
        nome=pessoa.nome,
        cpf=pessoa.cpf,
        empresa=pessoa.empresa,
        cliente=pessoa.cliente,
        email=usuario.email
    )

@router.post("/user/login")
def login(payload: UsuarioLogin, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == payload.email).first()

    if not usuario or usuario.senha != payload.senha:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    pessoa = db.query(Pessoa).filter(Pessoa.id == usuario.id_pessoa).first()

    # Tokens
    auth_token = criar_token({"id": pessoa.id}, expires_in=2)
    refresh_token = criar_token({"id": pessoa.id, "tipo": "refresh"}, expires_in=10)
    logged_token = criar_token({"logged": True}, expires_in=2)

    response = JSONResponse(content={"message": "Login com sucesso"})
    response.set_cookie("access_token", auth_token, httponly=True, path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, path="/")
    response.set_cookie("logged_user", logged_token, httponly=True, path="/")

    return response

@router.get("/user/me", response_model=PessoaResponse)
def get_me(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Token de autenticação ausente")

    payload = verificar_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")

    pessoa = db.query(Pessoa).filter(Pessoa.id == payload.get("id")).first()
    usuario = db.query(Usuario).filter(Usuario.id_pessoa == pessoa.id).first()

    if not pessoa or not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    return PessoaResponse(
        nome=pessoa.nome,
        cpf=pessoa.cpf,
        empresa=pessoa.empresa,
        cliente=pessoa.cliente,
        email=usuario.email
    )

@router.post("/user/refresh")
def refresh_token(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=400, detail="refreshToken não fornecido")

    payload = verificar_token(token)
    if not payload or payload.get("tipo") != "refresh":
        raise HTTPException(status_code=401, detail="refreshToken inválido ou expirado")

    pessoa = db.query(Pessoa).filter(Pessoa.id == payload.get("id")).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    novo_auth = criar_token({"id": pessoa.id}, expires_in=2)
    novo_logged = criar_token({"logged": True}, expires_in=2)

    response = JSONResponse(content={"message": "Token renovado"})
    response.set_cookie("access_token", novo_auth, httponly=True, path="/")
    response.set_cookie("logged_user", novo_logged, httponly=True, path="/")

    return response
