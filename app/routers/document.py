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
from app.schemas.document import TipoDocumentoResponse, StatusDocCreate, StatusDocOut, StatusDocOutWithFile
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

def _to_str_date(v) -> str:
    # v é datetime.date
    return v.isoformat() if v is not None else None

def _to_str_time(v) -> str:
    # v é datetime.time
    return v.strftime("%H:%M:%S") if v is not None else None

def _record_to_out(obj: StatusDocumento) -> StatusDocOutWithFile:
    b64 = base64.b64encode(obj.arquivo).decode("utf-8") if obj.arquivo else None
    return StatusDocOutWithFile(
        id=obj.id,
        aceito=bool(obj.aceito),
        ip_usuario=str(obj.ip_usuario),
        tipo_doc=str(obj.tipo_doc),
        data=_to_str_date(obj.data),
        hora=_to_str_time(obj.hora),
        cpf=(obj.cpf if obj.cpf is not None else None),
        matricula=(obj.matricula if obj.matricula is not None else None),
        unidade=(obj.unidade if obj.unidade is not None else None),
        competencia=(obj.competencia if obj.competencia is not None else None),
        base64=b64,
    )

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

        return registro
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao gravar no banco: {getattr(e, 'orig', e)}")

@router.get(
    "/status-doc/{id}",
    response_model=StatusDocOutWithFile,
    summary="Obtém um registro por ID com arquivo em Base64",
)
def get_status_doc_by_id(id: int, db: Session = Depends(get_db)):
    obj = db.get(StatusDocumento, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return _record_to_out(obj)