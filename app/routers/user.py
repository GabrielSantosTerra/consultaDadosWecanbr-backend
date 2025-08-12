from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.utils.jwt_handler import decode_token
from datetime import datetime
import re
import os

from app.utils.password import gerar_hash_senha, verificar_senha
from app.database.connection import get_db
from app.models.user import Usuario, Pessoa
from app.models.blacklist import TokenBlacklist
from app.schemas.user import CadastroPessoa, UsuarioLogin, PessoaResponse, CadastroColaborador, ColabResponse
from app.utils.jwt_handler import criar_token, verificar_token, decode_token
from dotenv import load_dotenv

router = APIRouter()

load_dotenv()
is_prod = os.getenv('ENVIRONMENT') == "prod"

cookie_env = {
    "secure": is_prod,
    "samesite": "Strict" if is_prod else "Lax"
}

@router.post(
    "/user/register",
    response_model=None,
    status_code=status.HTTP_201_CREATED
)
def registrar_usuario(
    payload: CadastroPessoa,
    db: Session = Depends(get_db),
):
    # 1) CPF não pode existir
    if db.query(Pessoa).filter(Pessoa.cpf == payload.pessoa.cpf).first():
        raise HTTPException(400, "CPF já cadastrado")
    # 2) Email não pode existir
    if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
        raise HTTPException(400, "Email já cadastrado")

    # 3) Cria Pessoa
    pessoa = Pessoa(**payload.pessoa.dict())
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)

    # 4) Cria Usuário, usando o ID gerado de Pessoa
    usuario = Usuario(
        id_pessoa=pessoa.id,
        email=payload.usuario.email,
        senha=gerar_hash_senha(payload.usuario.senha)
    )
    db.add(usuario)
    db.commit()

    return pessoa

# @router.post("/user/register_colab", response_model=ColabResponse)
# def registrar_colaborador(payload: CadastroColaborador, db: Session = Depends(get_db)):
#     if db.query(Usuario).filter(Usuario.email == payload.usuario.email).first():
#         raise HTTPException(status_code=400, detail="Email já cadastrado")

#     colab = Pessoa(**payload.pessoa.dict())  # centro_de_custo, cliente, matricula já incluídos
#     db.add(colab)
#     db.commit()
#     db.refresh(colab)

#     try:
#         usuario = Usuario(
#             id_pessoa=colab.id,
#             email=payload.usuario.email,
#             senha=gerar_hash_senha(payload.usuario.senha)
#         )
#         db.add(usuario)
#         db.commit()
#     except Exception:
#         db.rollback()
#         raise HTTPException(status_code=500, detail="Erro ao salvar usuário")

#     return ColabResponse(
#         nome=colab.nome,
#         cpf=colab.cpf,
#         cliente=colab.cliente,
#         centro_de_custo=colab.centro_de_custo,
#         matricula=colab.matricula,
#         email=usuario.email
#     )

# @router.post("/user/login", response_model=None, status_code=status.HTTP_200_OK)
# def login(
#     payload: UsuarioLogin,
#     db: Session = Depends(get_db),
# ):
#     def is_email(valor: str) -> bool:
#         return re.match(r"[^@]+@[^@]+\.[^@]+", valor) is not None

#     if is_email(payload.usuario):
#         usuario = db.query(Usuario).filter(Usuario.email == payload.usuario).first()
#     else:
#         pessoa = db.query(Pessoa).filter(Pessoa.cpf == payload.usuario).first()
#         if not pessoa:
#             raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
#         usuario = db.query(Usuario).filter(Usuario.id_pessoa == pessoa.id).first()

#     # CHANGED: verificação direta de igualdade, sem chamar verificar_senha()
#     if not usuario or payload.senha != usuario.senha:
#         raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

#     access_token = criar_token(
#         {"id": usuario.id_pessoa},
#         expires_in=60 * 24 * 7
#     )
#     refresh_token = criar_token(
#         {"id": usuario.id_pessoa},
#         expires_in=60 * 24 * 30
#     )
#     response = JSONResponse(content={"message": "Login com sucesso"})
#     response.set_cookie(
#         "access_token",
#         access_token,
#         httponly=True,
#         path="/",
#         max_age=60 * 60 * 24 * 7,
#     )
#     response.set_cookie(
#         "refresh_token",
#         refresh_token,
#         httponly=True,
#         path="/",
#         max_age=60 * 60 * 24 * 30,
#     )
#     response.set_cookie(
#         "logged_user",
#         "true",
#         httponly=False,
#         path="/",
#         max_age=60 * 60 * 24 * 7,
#     )

#     return response

@router.post(
    "/user/login",
    response_model=None,
    status_code=status.HTTP_200_OK
)
def login_user(
    payload: UsuarioLogin,
    db: Session = Depends(get_db),
):
    # helper para distinguir e-mail vs CPF
    def is_email(valor: str) -> bool:
        return re.match(r"[^@]+@[^@]+\.[^@]+", valor) is not None

    # busca por e-mail ou CPF
    if is_email(payload.usuario):
        usuario = db.query(Usuario).filter(Usuario.email == payload.usuario).first()
    else:
        pessoa = db.query(Pessoa).filter(Pessoa.cpf == payload.usuario).first()
        if not pessoa:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
        usuario = db.query(Usuario).filter(Usuario.id_pessoa == pessoa.id).first()

    # agora verifica a senha corretamente contra o hash
    if not usuario or not verificar_senha(payload.senha, usuario.senha):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    # geração dos tokens
    access_token = criar_token(
        {"id": usuario.id_pessoa, "sub": usuario.email, "tipo": "access"},
        expires_in=60 * 24 * 7
    )
    refresh_token = criar_token(
        {"id": usuario.id_pessoa, "sub": usuario.email, "tipo": "refresh"},
        expires_in=60 * 24 * 30
    )

    # monta a resposta com cookies
    response = JSONResponse(content={"message": "Login com sucesso"})
    response.set_cookie(
        "access_token", access_token,
        httponly=True, max_age=60 * 60 * 24 * 7, path="/"
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, max_age=60 * 60 * 24 * 30, path="/"
    )
    response.set_cookie(
        "logged_user", "true",
        httponly=False, max_age=60 * 60 * 24 * 7, path="/"
    )

    return response

@router.get("/user/me", response_model=PessoaResponse)
def get_me(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Token de autenticação ausente")

    payload = verificar_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Token sem identificador único (jti)")

    if db.query(TokenBlacklist).filter_by(jti=jti).first():
        raise HTTPException(status_code=401, detail="Token expirado ou inválido")

    pessoa_id = payload.get("id")
    pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()

    if not pessoa:
        raise HTTPException(status_code=401, detail="Pessoa não encontrada")

    usuario = db.query(Usuario).filter(Usuario.id_pessoa == pessoa.id).first()

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    return PessoaResponse(
        nome=pessoa.nome,
        cpf=pessoa.cpf,
        email=usuario.email,
        cliente=pessoa.cliente,
        centro_de_custo=pessoa.centro_de_custo,
        matricula=pessoa.matricula,
        gestor=pessoa.gestor
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

    novo_auth = criar_token({"id": usuario.id_pessoa, "sub": usuario.email, "tipo": "access"}, expires_in=60 * 24 * 7)

    response = JSONResponse(content={"message": "Token renovado"})
    response.set_cookie("access_token", novo_auth, httponly=True, path="/", max_age=60 * 60 * 24 * 7, **cookie_env)
    response.set_cookie("logged_user", "true", httponly=False, path="/", max_age=60 * 60 * 24 * 7, **cookie_env)

    return response

@router.post("/user/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            jti = payload.get("jti")
            exp = datetime.fromtimestamp(payload.get("exp"))
            db.add(TokenBlacklist(jti=jti, expira_em=exp))
            db.commit()
        except Exception as e:
            print(f"[ERRO LOGOUT] {e}")  # ← LOG de erro
    else:
        print("[LOGOUT] Token não enviado")

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("logged_user", path="/")

    return {"message": "Logout realizado com sucesso"}