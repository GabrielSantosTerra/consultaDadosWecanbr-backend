from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from typing import List, Optional
import base64
import binascii
import requests
import re
import ipaddress

from app.database.connection import get_db
from app.schemas.document import TipoDocumentoResponse, StatusDocCreate, StatusDocOut
from app.models.document import TipoDocumento, StatusDocumento
from config.settings import settings
from app.utils.jwt_handler import verificar_token
from app.schemas.document import DeletarDocumentosRequest, DeletarDocumentosResponse


router = APIRouter()

BASE_URL = "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1"

def login(conta: str, usuario: str, senha: str) -> str:
    payload = {
        "conta": conta,
        "usuario": usuario,
        "senha": senha,
        "id_interface": "CLIENT_WEB"
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    response = requests.post(f"{BASE_URL}/login", data=payload, headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Erro ao autenticar no GED")

    data = response.json()
    if data.get("error"):
        raise HTTPException(status_code=401, detail="Login falhou")

    return data["authorization_key"]


def _extract_base64(raw: str) -> str:
    """Suporta tanto 'AAAA...' quanto 'data:...;base64,AAAA...'."""
    if not raw:
        return ""
    m = re.match(r"^data:.*?;base64,(.*)$", raw, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else raw

def _sanitize_ip(ip_raw: Optional[str]) -> str:
    """Normaliza e valida IPv4/IPv6 para coluna INET; se inválido, usa 0.0.0.0."""
    if not ip_raw:
        return "0.0.0.0"
    ip = ip_raw.strip()
    if "," in ip:  # X-Forwarded-For pode trazer lista
        ip = ip.split(",")[0].strip()
    # IPv4 com porta (1.2.3.4:12345)
    if ":" in ip and ip.count(":") == 1 and re.match(r"^\d{1,3}(\.\d{1,3}){3}:\d+$", ip):
        ip = ip.split(":")[0]
    # IPv6 com colchetes
    ip = ip.strip("[]")
    try:
        ipaddress.ip_address(ip)
        return ip
    except ValueError:
        return "0.0.0.0"

def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return _sanitize_ip(xff if xff else (request.client.host if request.client else None))


@router.get("/documents", response_model=List[TipoDocumentoResponse])
def listar_tipos_documentos(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Token de autenticação ausente")

    payload = verificar_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido")

    documentos = db.query(TipoDocumento).all()
    return documentos

@router.post("/documents/delete", response_model=DeletarDocumentosResponse)
def deletar_documentos_por_query(payload: DeletarDocumentosRequest):
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    # Buscar campos do template
    response_fields = requests.post(
        f"{BASE_URL}/templates/getfields",
        data={"id_template": payload.id_template},
        headers=headers
    )
    if response_fields.status_code != 200:
        raise HTTPException(status_code=500, detail="Falha ao buscar campos do template")

    campos_template = response_fields.json().get("fields", [])

    # Montar lista cp[]
    lista_cp = [""] * len(campos_template)
    for idx, campo in enumerate(campos_template):
        if campo.get("nomecampo") == payload.campo:
            lista_cp[idx] = payload.valor
            break

    # Payload de busca
    payload_busca = [("id_tipo", str(payload.id_template))]
    for valor in lista_cp:
        payload_busca.append(("cp[]", valor))

    payload_busca.extend([
        ("ordem", ""),
        ("dt_criacao", payload.dt_criacao or ""),
        ("pagina", "1"),
        ("colecao", "S")
    ])

    # Requisição de busca
    response_busca = requests.post(
        f"{BASE_URL}/documents/search",
        data=payload_busca,
        headers=headers
    )

    try:
        data = response_busca.json()
    except Exception:
        raise HTTPException(status_code=500, detail=f"Erro na resposta da GED: {response_busca.text}")

    if response_busca.status_code != 200 or data.get("error"):
        raise HTTPException(
            status_code=500,
            detail=f"Erro {response_busca.status_code}: {data.get('message', 'Erro desconhecido')}\nRaw: {response_busca.text}"
        )

    documentos = data.get("documents", [])
    total = len(documentos)
    deletados = 0
    erros = []

    for doc in documentos:
        delete_resp = requests.post(
            f"{BASE_URL}/documents/delete",
            data={
                "id_tipo": payload.id_template,
                "id_documento": doc["id_documento"]
            },
            headers=headers
        )
        if delete_resp.status_code == 200 and not delete_resp.json().get("error"):
            deletados += 1
        else:
            erros.append({"id_documento": doc["id_documento"], "erro": delete_resp.text})

    return {
        "total_encontrados": total,
        "total_deletados": deletados,
        "falhas": erros
    }

@router.post(
    "/status-doc",
    response_model=StatusDocOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grava aceite e arquivo (sem autenticação)",
)
def criar_status_doc(payload: StatusDocCreate, request: Request, db: Session = Depends(get_db)):
    try:
        b64 = _extract_base64(payload.base64)
        arquivo_bytes = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="base64 inválido")

    ip = _get_client_ip(request)

    registro = StatusDocumento(
        aceito=payload.aceito,
        ip_usuario=ip,
        tipo_doc=payload.tipo_doc,
        cpf=payload.cpf,
        matricula=payload.matricula,
        unidade=payload.unidade,
        competencia=payload.competencia,
        arquivo=arquivo_bytes,
    )
    try:
        db.add(registro)
        db.commit()
        db.refresh(registro)

        ok = db.execute(text("SELECT 1 FROM tb_status_doc WHERE id = :id"), {"id": registro.id}).scalar()
        if not ok:
            sch = db.execute(text("SELECT current_schema() AS sch")).first()
            raise HTTPException(
                status_code=500,
                detail=f"Commit efetuado, mas não encontrei id={registro.id} em tb_status_doc (schema={sch.sch}). "
                       f"Verifique search_path/schema do model e onde você está consultando."
            )
        return registro
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao gravar no banco: {getattr(e, 'orig', e)}")
