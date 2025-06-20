from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import timedelta
import re

from app.utils.password import gerar_hash_senha, verificar_senha  # <-- adiciona
from app.database.connection import get_db
from app.models.user import Usuario, Pessoa
from app.schemas.user import CadastroPessoa, UsuarioLogin, PessoaResponse, CadastroColaborador, ColabResponse
from app.utils.jwt_handler import criar_token, verificar_token

router = APIRouter()

@router.post("/user/register", response_model=PessoaResponse)
def registrar_usuario(payload: CadastroPessoa, db: Session = Depends(get_db)):
    if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    pessoa = Pessoa(
        nome=payload.pessoa.nome,
        cpf=payload.pessoa.cpf,
    )
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)

    try:
        usuario = Usuario(
            id_pessoa=pessoa.id,
            email=payload.usuario.email,
            senha=gerar_hash_senha(payload.usuario.senha)
        )
        db.add(usuario)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao salvar usuário")

    return PessoaResponse(
        nome=pessoa.nome,
        cpf=pessoa.cpf,
        email=usuario.email
    )

@router.post("/user/register_colab", response_model=ColabResponse)
def registrar_colaborador(payload: CadastroColaborador, db: Session = Depends(get_db)):
    if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado")

    colab = Pessoa(**payload.pessoa.dict())  # centro_de_custo, cliente, matricula já incluídos
    db.add(colab)
    db.commit()
    db.refresh(colab)

    try:
        usuario = Usuario(
            id_pessoa=colab.id,
            email=payload.usuario.email,
            senha=gerar_hash_senha(payload.usuario.senha)
        )
        db.add(usuario)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao salvar usuário")

    return ColabResponse(
        nome=colab.nome,
        cpf=colab.cpf,
        cliente=colab.cliente,
        centro_de_custo=colab.centro_de_custo,
        matricula=colab.matricula,
        email=usuario.email
    )

@router.post("/user/login")
def login(payload: UsuarioLogin, db: Session = Depends(get_db)):
    def is_email(valor: str) -> bool:
        return re.match(r"[^@]+@[^@]+\.[^@]+", valor) is not None

    if is_email(payload.usuario):
        usuario = db.query(Usuario).filter(Usuario.email == payload.usuario).first()
    else:
        pessoa = db.query(Pessoa).filter(Pessoa.cpf == payload.usuario).first()
        if not pessoa:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
        usuario = db.query(Usuario).filter(Usuario.id_pessoa == pessoa.id).first()

    if not usuario or not verificar_senha(payload.senha, usuario.senha):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    pessoa = db.query(Pessoa).filter(Pessoa.id == usuario.id_pessoa).first()

    auth_token = criar_token({"id": pessoa.id}, expires_in=60 * 24 * 7)
    refresh_token = criar_token({"id": pessoa.id, "tipo": "refresh"}, expires_in=60 * 24 * 30)
    logged_token = criar_token({"logged": True}, expires_in=60 * 24 * 7)

    response = JSONResponse(content={"message": "Login com sucesso"})
    response.set_cookie("access_token", auth_token, httponly=True, path="/", max_age=60 * 60 * 24 * 7, secure=True, samesite="None")
    response.set_cookie("refresh_token", refresh_token, httponly=True, path="/", max_age=60 * 60 * 24 * 30, secure=True, samesite="None")
    response.set_cookie("logged_user", logged_token, httponly=True, path="/", max_age=60 * 60 * 24 * 7, secure=True, samesite="None")

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

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")

    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    novo_auth = criar_token({"sub": usuario.email}, expires_in=60 * 24 * 7)
    novo_logged = criar_token({"logged": True}, expires_in=60 * 24 * 7)

    response = JSONResponse(content={"message": "Token renovado"})
    response.set_cookie("access_token", novo_auth, httponly=True, path="/", max_age=60 * 60 * 24 * 7, secure=True, samesite="None")
    response.set_cookie("logged_user", novo_logged, httponly=True, path="/", max_age=60 * 60 * 24 * 7, secure=True, samesite="None")

    return response

@router.post("/user/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/", samesite="None", secure=True)
    response.delete_cookie("refresh_token", path="/", samesite="None", secure=True)
    response.delete_cookie("logged_user", path="/", samesite="None", secure=True)

    return {"message": "Logout realizado com sucesso"}
