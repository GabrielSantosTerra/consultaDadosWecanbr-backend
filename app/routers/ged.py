from fastapi import APIRouter, HTTPException, Form
from typing import Any
import requests
from pydantic import BaseModel
from fastapi.responses import JSONResponse
import base64
from config.settings import settings
from typing import List
from io import BytesIO
from pdf2image import convert_from_bytes
from PIL import Image

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

@router.post("/searchdocuments/allDocuments")
def listar_todos_arquivos_por_template(id_tipo: int = Form(...)):
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1;"
    }

    payload = f"id_tipo={id_tipo}&cp[]=&ordem=&dt_criacao=&pagina=1&colecao=S"

    response = requests.post(f"{BASE_URL}/documents/search", headers=headers, data=payload)

    if response.status_code != 200:
        return JSONResponse(
            status_code=response.status_code,
            content={"error": "Erro na requisição", "status_code": response.status_code, "body": response.text}
        )

    try:
        data = response.json()
        for doc in data.get("documents", []):
            attributes = doc.pop("attributes", [])
            for attr in attributes:
                doc[attr["name"]] = attr["value"]
        return JSONResponse(content=data)

    except Exception:
        return JSONResponse(
            status_code=200,
            content={"warning": "Resposta não está em JSON", "raw": response.text}
        )

@router.post("/searchdocuments/documents")
def buscar_documento_por_campos(payload: BuscaDocumentoCampos):
    # Login GED
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
    nomes_campos = [campo["nomecampo"] for campo in campos_template]
    # Inicializa cp[] com valores vazios na ordem dos campos do template
    lista_cp = ["" for _ in nomes_campos]

    # Preenche cp[] nas posições corretas
    for item in payload.cp:
        if item.nome not in nomes_campos:
            raise HTTPException(status_code=400, detail=f"Campo '{item.nome}' não encontrado no template")
        idx = nomes_campos.index(item.nome)
        lista_cp[idx] = item.valor

    # Montar payload com múltiplos cp[]
    payload_busca = [("id_tipo", str(payload.id_template))]
    payload_busca.extend([("cp[]", valor) for valor in lista_cp])
    payload_busca.extend([
        ("ordem", ""),
        ("dt_criacao", ""),
        ("pagina", "1"),
        ("colecao", "S")
    ])

    # Requisição ao GED
    response_busca = requests.post(
        f"{BASE_URL}/documents/search",
        data=payload_busca,
        headers=headers
    )

    try:
        data = response_busca.json()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail=f"Erro na resposta da GED: {response_busca.text}"
        )

    if data.get("error"):
        raise HTTPException(
            status_code=500,
            detail=f"Erro {response_busca.status_code}: {data.get('message', 'Erro desconhecido')}\nRaw: {response_busca.text}"
        )

    # Extrair atributos
    for doc in data.get("documents", []):
        attributes = doc.pop("attributes", [])
        for attr in attributes:
            doc[attr["name"]] = attr["value"]

    return JSONResponse(content=data)

@router.post("/searchdocuments/download")
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