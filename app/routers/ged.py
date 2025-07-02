from fastapi import APIRouter, HTTPException, Form
from typing import Any
import requests
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from datetime import datetime
from dateutil.relativedelta import relativedelta
import base64
from config.settings import settings
from typing import List
from io import BytesIO
# from pdf2image import convert_from_bytes
# from PIL import Image

router = APIRouter()

class TemplateFieldsRequest(BaseModel):
    id_template: int

class DocumentoGED(BaseModel):
    id_documento: str
    nomearquivo: str
    datacriacao: str
    cpf: str = ""
    datadevencimento: str = ""
    nossonumero: str = ""

class CampoConsulta(BaseModel):
    nome: str
    valor: str

class BuscaDocumentoCampos(BaseModel):
    id_template: int
    cp: List[CampoConsulta]

class DownloadDocumentoPayload(BaseModel):
    id_tipo: int
    id_documento: int

class CampoValor(BaseModel):
    nome: str
    valor: str

class UltimosDocumentosRequest(BaseModel):
    id_template: int
    cp: List[CampoValor]  # incluirá matrícula como no modelo atual
    campo_anomes: str

class UploadBase64Payload(BaseModel):
    id_tipo: int
    formato: str
    documento_nome: str
    documento_base64: str
    campos: List[CampoConsulta]

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

@router.get("/searchdocuments/templates")
def listar_templates() -> Any:
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key
    }

    response = requests.get(f"{BASE_URL}/templates/getall", headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Erro ao buscar templates")

    data = response.json()

    if data.get("error"):
        raise HTTPException(status_code=400, detail="Erro na resposta da API GED")

    # Retorna diretamente o conteúdo da chave "templates"
    return data.get("templates", [])

@router.post("/searchdocuments/templateFields")
def get_template_fields(id_template: int = Form(...)):
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    payload = f"id_template={id_template}"

    response = requests.post(
        "http://ged.byebyepaper.com.br:9090/idocs_bbpaper/api/v1/templates/getfields",
        headers=headers,
        data=payload
    )

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Erro ao buscar campos do template")

    return response.json()

@router.post("/documents/upload_base64")
def upload_documento_base64(payload: UploadBase64Payload):
    # 1. Login primeiro
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    # 2. Buscar campos do template
    response_fields = requests.post(
        f"{BASE_URL}/templates/getfields",
        data={"id_template": payload.id_tipo},
        headers=headers
    )
    if response_fields.status_code != 200:
        raise HTTPException(status_code=500, detail="Erro ao buscar campos do template")

    campos_template = response_fields.json().get("fields", [])
    nomes_campos = [campo["nomecampo"] for campo in campos_template]
    lista_cp = ["" for _ in nomes_campos]

    # 3. Preencher cp[] na ordem correta
    for campo in payload.campos:
        if campo.nome not in nomes_campos:
            raise HTTPException(status_code=400, detail=f"Campo '{campo.nome}' não encontrado no template")
        idx = nomes_campos.index(campo.nome)
        lista_cp[idx] = campo.valor

    # 4. Montar payload
    data = {
        "id_tipo": str(payload.id_tipo),
        "formato": payload.formato,
        "documento_nome": payload.documento_nome,
        "documento": payload.documento_base64
    }
    for valor in lista_cp:
        data.setdefault("cp[]", []).append(valor)

    # 5. Enviar para GED
    response = requests.post(
        f"{BASE_URL}/documents/uploadbase64",
        headers=headers,
        data=data
    )

    try:
        return response.json()
    except Exception:
        raise HTTPException(status_code=500, detail=f"Erro no upload: {response.text}")

@router.post("/documents/ultimos")
def buscar_ultimos_documentos(payload: UltimosDocumentosRequest):
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )
    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    # Buscar estrutura dos campos
    response_fields = requests.post(
        f"{BASE_URL}/templates/getfields",
        data={"id_template": payload.id_template},
        headers=headers
    )
    if response_fields.status_code != 200:
        raise HTTPException(status_code=500, detail="Erro ao buscar campos do template")

    campos_template = response_fields.json().get("fields", [])
    nomes_campos = [campo["nomecampo"] for campo in campos_template]
    lista_cp = ["" for _ in nomes_campos]

    for item in payload.cp:
        if item.nome not in nomes_campos:
            raise HTTPException(status_code=400, detail=f"Campo '{item.nome}' não encontrado no template")
        idx = nomes_campos.index(item.nome)
        lista_cp[idx] = item.valor

    if payload.campo_anomes not in nomes_campos:
        raise HTTPException(status_code=400, detail=f"Campo '{payload.campo_anomes}' não encontrado no template")

    # Busca geral sem filtro por anomes
    payload_busca = [("id_tipo", str(payload.id_template))]
    payload_busca.extend([("cp[]", valor) for valor in lista_cp])
    payload_busca.extend([
        ("ordem", ""),
        ("dt_criacao", ""),
        ("pagina", "1"),
        ("colecao", "S")
    ])

    response_busca = requests.post(
        f"{BASE_URL}/documents/search",
        data=payload_busca,
        headers=headers
    )

    try:
        data = response_busca.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao interpretar resposta da GED")

    if data.get("error"):
        raise HTTPException(status_code=500, detail=f"Erro: {data.get('message')}")

    documentos_total = []

    for doc in data.get("documents", []):
        attributes = doc.pop("attributes", [])
        for attr in attributes:
            doc[attr["name"]] = attr["value"]
        documentos_total.append(doc)

    # ✅ Filtro: apenas com campo_anomes presente e não vazio
    documentos_validos = [
        d for d in documentos_total
        if payload.campo_anomes in d and d[payload.campo_anomes]
    ]

    # ✅ Ordenar pelo campo anomes
    documentos_validos.sort(key=lambda d: d[payload.campo_anomes], reverse=True)

    return JSONResponse(content={
        "documentos": documentos_validos[:3],
        "total_encontrado": len(documentos_total)
    })

@router.post("/searchdocuments/download") #Fazer com que ao baixar o documento ele de um log de quem baixou
def baixar_documento(payload: DownloadDocumentoPayload):
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

    data = {
        "id_tipo": payload.id_tipo,
        "id_documento": payload.id_documento
    }

    response = requests.post(
        f"{BASE_URL}/documents/download",
        headers=headers,
        data=data
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Erro {response.status_code}: {response.text}")

    try:
        return response.json()  # Se a resposta for JSON com {"base64": "..."}
    except ValueError:
        return {
            "erro": False,
            "base64_raw": response.text  # pode ser o próprio base64 direto
        }

# @router.post("/searchdocuments/download_image")
# def baixar_documento_convertido(payload: DownloadDocumentoPayload):
#     auth_key = login(
#         conta=settings.GED_CONTA,
#         usuario=settings.GED_USUARIO,
#         senha=settings.GED_SENHA
#     )

#     headers = {
#         "Authorization": auth_key,
#         "Content-Type": "application/x-www-form-urlencoded"
#     }

#     data = {
#         "id_tipo": payload.id_tipo,
#         "id_documento": payload.id_documento
#     }

#     response = requests.post(f"{BASE_URL}/documents/download", headers=headers, data=data)

#     if response.status_code != 200:
#         raise HTTPException(status_code=500, detail="Erro ao baixar documento")

#     try:
#         pdf_bytes = base64.b64decode(response.text)  # base64 vem direto como string

#         # Poppler path
#         images = convert_from_bytes(pdf_bytes, poppler_path=r"C:\poppler-24.08.0\Library\bin")
#         first_image = images[0]

#         # Converte para base64
#         buffer = BytesIO()
#         first_image.save(buffer, format="JPEG")
#         img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
#         print(img_base64)
#         return JSONResponse(content={"image_base64": img_base64})

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Erro ao converter PDF para imagem: {str(e)}")