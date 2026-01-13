from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.utils.jwt_handler import decode_token
from datetime import datetime
import re
import os
from typing import List

from app.utils.password import gerar_hash_senha, verificar_senha
from app.database.connection import get_db
from app.models.user import Usuario, Pessoa
from app.models.blacklist import TokenBlacklist
from app.schemas.user import AtualizarSenhaRequest, CadastroPessoa, UsuarioLogin, PessoaResponse, DadoItem
from app.utils.jwt_handler import criar_token, verificar_token, decode_token
from dotenv import load_dotenv

router = APIRouter()

load_dotenv()
is_prod = os.getenv('ENVIRONMENT') == "prod"

cookie_domain = "ziondocs.com.br" if is_prod else None

cookie_env = {
    "secure": True if is_prod else False,
    "samesite": "Lax",
    "domain": cookie_domain
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

    if not usuario or not payload.senha == usuario.senha:
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
        httponly=True, max_age=60 * 60 * 24 * 7, path="/", **cookie_env
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, max_age=60 * 60 * 24 * 30, path="/", **cookie_env
    )
    response.set_cookie(
        "logged_user", "true",
        httponly=False, max_age=60 * 60 * 24 * 7, path="/", **cookie_env
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

    # normaliza CPF e matrícula
    cpf_pessoa = str(pessoa.cpf or "").strip()
    mat_pessoa = str(getattr(pessoa, "matricula", "") or "").strip()

    # 1) Busca TODOS os clientes que aparecem em tb_holerite_cabecalhos
    #    para o CPF OU para a matrícula da pessoa
    sql_dados = text("""
        SELECT DISTINCT
               TRIM(c.cliente::text)   AS id,
               TRIM(c.cliente_nome)    AS nome,
               TRIM(c.matricula::text) AS mat
        FROM tb_holerite_cabecalhos c
        WHERE
            (
                regexp_replace(TRIM(c.cpf::text), '[^0-9]', '', 'g')
                = regexp_replace(TRIM(:cpf), '[^0-9]', '', 'g')
                OR
                (TRIM(:matricula) <> '' AND TRIM(c.matricula::text) = TRIM(:matricula))
            )
          AND c.matricula IS NOT NULL AND TRIM(c.matricula::text) <> ''
          AND c.cliente  IS NOT NULL AND TRIM(c.cliente::text)  <> ''
        ORDER BY nome NULLS LAST, id, mat
    """)

    rows = db.execute(
        sql_dados,
        {"cpf": cpf_pessoa, "matricula": mat_pessoa},
    ).fetchall()

    dados: List[DadoItem] = [
        DadoItem(id=row[0], nome=row[1], matricula=row[2])
        for row in rows
    ]

    # mapa cliente_id -> nome, quando já conhecido
    nomes_por_cliente = {
        str(row[0]).strip(): row[1]
        for row in rows
        if row[1]
    }

    # 2) Garante que o cliente principal da tabela Pessoa também esteja em "dados"
    if mat_pessoa and getattr(pessoa, "cliente", None):
        cli_pessoa = str(pessoa.cliente).strip()

        ja_existe_vinculo = any(
            d.id == cli_pessoa and d.matricula == mat_pessoa
            for d in dados
        )

        if not ja_existe_vinculo:
            nome_cliente = nomes_por_cliente.get(cli_pessoa)

            # fallback: tenta descobrir o nome do cliente em QUALQUER holerite desse cliente
            if not nome_cliente:
                sql_nome_cliente = text("""
                    SELECT TRIM(c.cliente_nome) AS nome
                    FROM tb_holerite_cabecalhos c
                    WHERE TRIM(c.cliente::text) = TRIM(:cliente)
                      AND c.cliente_nome IS NOT NULL
                      AND TRIM(c.cliente_nome) <> ''
                    ORDER BY c.cliente_nome
                    LIMIT 1
                """)
                nome_cliente = db.execute(
                    sql_nome_cliente,
                    {"cliente": cli_pessoa},
                ).scalar()

            dados.insert(
                0,
                DadoItem(
                    id=cli_pessoa,
                    nome=nome_cliente,
                    matricula=mat_pessoa,
                ),
            )

    return PessoaResponse(
        nome=pessoa.nome,
        cpf=str(pessoa.cpf),
        email=str(usuario.email),
        cliente=getattr(pessoa, "cliente", None),
        centro_de_custo=getattr(pessoa, "centro_de_custo", None),
        gestor=bool(getattr(pessoa, "gestor", False)),
        rh=bool(getattr(pessoa, "rh", False)),
        senha_trocada=bool(getattr(usuario, "senha_trocada", False)),  # <-- NOVO
        dados=dados,
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

    response.delete_cookie("access_token", path="/", domain=cookie_domain)
    response.delete_cookie("refresh_token", path="/", domain=cookie_domain)
    response.delete_cookie("logged_user", path="/", domain=cookie_domain)

    return {"message": "Logout realizado com sucesso"}

from fastapi import HTTPException, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

@router.put("/user/update-password")
def update_password(
    body: AtualizarSenhaRequest,
    request: Request,
    db: Session = Depends(get_db),
):
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

    # Normaliza CPF enviado e CPF do usuário autenticado
    cpf_body = "".join(ch for ch in str(body.cpf or "") if ch.isdigit())
    cpf_pessoa = "".join(ch for ch in str(pessoa.cpf or "") if ch.isdigit())

    if not cpf_body or cpf_body != cpf_pessoa:
        raise HTTPException(status_code=403, detail="CPF não confere com o usuário autenticado")

    if body.senha_atual == body.senha_nova:
        raise HTTPException(status_code=400, detail="A nova senha não pode ser igual à senha antiga")

    # 1) Confere se existe ao menos um usuário daquele CPF com a senha atual informada
    sql_check = text("""
        SELECT 1
        FROM app_rh.tb_usuario u
        JOIN app_rh.tb_pessoa p ON p.id = u.id_pessoa
        WHERE
            regexp_replace(TRIM(p.cpf::text), '[^0-9]', '', 'g')
                = regexp_replace(TRIM(:cpf), '[^0-9]', '', 'g')
            AND COALESCE(u.senha::text, '') = :senha_atual
        LIMIT 1
    """)

    ok = db.execute(
        sql_check,
        {"cpf": cpf_body, "senha_atual": body.senha_atual},
    ).scalar()

    if not ok:
        raise HTTPException(status_code=400, detail="Senha antiga incorreta")

    # 2) Atualiza TODOS os vínculos do CPF (todas as empresas)
    sql_update = text("""
        UPDATE app_rh.tb_usuario u
        SET
            senha = :senha_nova,
            senha_trocada = TRUE
        FROM app_rh.tb_pessoa p
        WHERE
            u.id_pessoa = p.id
            AND regexp_replace(TRIM(p.cpf::text), '[^0-9]', '', 'g')
                = regexp_replace(TRIM(:cpf), '[^0-9]', '', 'g')
    """)

    result = db.execute(
        sql_update,
        {"senha_nova": body.senha_nova, "cpf": cpf_body},
    )
    db.commit()

    updated_rows = result.rowcount or 0
    if updated_rows == 0:
        raise HTTPException(status_code=404, detail="Nenhum usuário encontrado para o CPF informado")

    return {
        "message": "Senha atualizada com sucesso",
        "senha_trocada": True,
        "usuarios_atualizados": updated_rows,
    }

