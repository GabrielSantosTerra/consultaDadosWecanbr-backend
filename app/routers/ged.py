from urllib import response
from fastapi import APIRouter, HTTPException, Form, Depends, Response
from typing import Any, Literal, Dict, Optional, Set
import requests
from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi.responses import JSONResponse
from datetime import datetime
from babel.dates import format_date
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.connection import get_db
from config.settings import settings
from typing import List
from io import BytesIO
import io
import re
import base64
from fpdf import FPDF
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

class SearchDocumentosRequest(BaseModel):
    id_template: int | str
    cp: List[CampoValor] = Field(default_factory=list)
    campo_anomes: str
    anomes: Optional[str] = None           # ex.: "2025-05", "202505", "2025/05", "05/2025"
    anomes_in: Optional[List[str]] = None  # ex.: ["2025-05", "2025-02"]

    @field_validator("campo_anomes")
    @classmethod
    def _valida_campo_anomes(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("campo_anomes é obrigatório")
        return v

    # >>> NOVO: trata vazio como None
    @field_validator("anomes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    # >>> NOVO: limpa lista vazia / strings vazias
    @field_validator("anomes_in", mode="before")
    @classmethod
    def _normalize_anomes_in(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, list):
            cleaned = [str(x).strip() for x in v if str(x).strip()]
            return cleaned or None
        s = str(v).strip()
        return [s] if s else None

class BuscarHolerite(BaseModel):
    cpf: str = Field(..., min_length=11, max_length=14, description="CPF sem formatação, 11 dígitos")
    matricula: str
    competencia: str

class MontarHolerite(BaseModel):
    matricula: str
    competencia: str
    lote: str
    cpf: str = Field(
        ...,
        pattern=r'^\d{11}$',
        description="CPF sem formatação, 11 dígitos (ex: 06485294015)"
    )

class UploadBase64Payload(BaseModel):
    id_tipo: int
    formato: str
    documento_nome: str
    documento_base64: str
    campos: List[CampoConsulta]

def _normaliza_anomes(valor: str) -> str | None:
    v = (valor or "").strip()
    if not v:
        return None
    try:
        datetime.strptime(v, "%Y-%m")
        return v
    except ValueError:
        pass
    if len(v) == 6 and v.isdigit():          # YYYYMM
        return f"{v[:4]}-{v[4:]}"
    if "/" in v:                              # YYYY/MM ou MM/YYYY
        a, b = v.split("/", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
        if len(b) == 4 and a.isdigit():
            return f"{b}-{a.zfill(2)}"
    if "-" in v:                              # YYYY-M
        a, b = v.split("-", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
    return None

def _flatten_attributes(document: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(document)
    for a in (d.pop("attributes", []) or []):
        n, val = a.get("name"), a.get("value")
        if n:
            d[n] = val
    return d

def _split_competencia(raw: str) -> tuple[int, str]:
    """
    Aceita formatos: 'YYYYMM', 'YYYY-MM', 'YYYY-MM-DD'
    Retorna: (ano:int, mes:'MM')
    """
    s = str(raw).strip()
    if "-" in s:
        # pega até 'YYYY-MM'
        partes = s.split("-")
        if len(partes) >= 2:
            ano = int(partes[0])
            mes = partes[1][:2].zfill(2)
            return ano, mes
        # fallback
        s = "".join(partes)
    # formatos compactos
    if len(s) >= 6:
        ano = int(s[:4])
        mes = s[4:6]
        return ano, mes
    raise ValueError(f"Formato de competência inválido: {raw}")

def _headers(auth_key: str) -> Dict[str, str]:
    return {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1",
    }

def _normaliza_anomes(valor: str) -> Optional[str]:
    v = (valor or "").strip()
    if not v:
        return None
    try:
        datetime.strptime(v, "%Y-%m")
        return v
    except ValueError:
        pass
    if len(v) == 6 and v.isdigit():          # YYYYMM
        return f"{v[:4]}-{v[4:]}"
    if "/" in v:                              # YYYY/MM ou MM/YYYY
        a, b = v.split("/", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
        if len(b) == 4 and a.isdigit():
            return f"{b}-{a.zfill(2)}"
    if "-" in v:                              # YYYY-M
        a, b = v.split("-", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
    return None

def _flatten_attributes(document: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(document)
    for a in (d.pop("attributes", []) or []):
        n, val = a.get("name"), a.get("value")
        if n:
            d[n] = val
    return d

# >>> NOVO: converte "YYYY-MM" em {"ano": YYYY, "mes": MM}
def _to_ano_mes(yyyymm: str) -> Dict[str, int]:
    ano_str, mes_str = yyyymm.split("-", 1)
    return {"ano": int(ano_str), "mes": int(mes_str)}

def _coleta_anomes_via_search(
    headers: Dict[str, str],
    id_template: int | str,
    nomes_campos: List[str],
    lista_cp: List[str],
    campo_anomes: str,
    max_pages: int = 10
) -> List[str]:
    """
    Fallback quando /documents/filter falha:
    Consulta /documents/search paginando e extrai valores únicos do campo_anomes.
    Retorna normalizado no formato "YYYY-MM".
    """
    meses: Set[str] = set()
    pagina = 1
    total_paginas = 1  # assume 1 até ler o retorno

    while pagina <= total_paginas and pagina <= max_pages:
        form = [("id_tipo", str(id_template))]
        form += [("cp[]", v) for v in lista_cp]  # aqui só tipodedoc/matricula terão valor
        form += [
            ("ordem", "no_ordem"),
            ("dt_criacao", ""),
            ("pagina", str(pagina)),
            ("colecao", "S"),
        ]

        r = requests.post(f"{BASE_URL}/documents/search", data=form, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json() or {}

        docs = [_flatten_attributes(doc) for doc in (data.get("documents") or [])]
        for d in docs:
            bruto = str(d.get(campo_anomes, "")).strip()
            n = _normaliza_anomes(bruto)
            if n:
                meses.add(n)

        vars_ = data.get("variables") or {}
        try:
            total_paginas = int(vars_.get("totalpaginas", total_paginas))
        except Exception:
            total_paginas = 1

        pagina += 1

    return sorted(meses, reverse=True)


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

# @router.post("/documents/search")
# def buscar_search_documentos(payload: SearchDocumentosRequest):
#     # 1) Autentica no GED
#     auth_key = login(
#         conta=settings.GED_CONTA,
#         usuario=settings.GED_USUARIO,
#         senha=settings.GED_SENHA
#     )
#     headers = {
#         "Authorization": auth_key,
#         "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
#     }

#     # 2) Obtém definição de campos do template
#     resp_fields = requests.post(
#         f"{BASE_URL}/templates/getfields",
#         data={"id_template": payload.id_template},
#         headers=headers
#     )
#     resp_fields.raise_for_status()
#     nomes_campos = [f["nomecampo"] for f in resp_fields.json().get("fields", [])]

#     # 3) Monta a lista cp[] na ordem exata
#     lista_cp = ["" for _ in nomes_campos]
#     for item in payload.cp:
#         if item.nome not in nomes_campos:
#             raise HTTPException(400, f"Campo '{item.nome}' não existe no template")
#         lista_cp[nomes_campos.index(item.nome)] = item.valor

#     if payload.campo_anomes not in nomes_campos:
#         raise HTTPException(400, f"Campo '{payload.campo_anomes}' não existe no template")

#     # 4) Monta payload de busca (id_tipo, cp[], ordem, dt_criacao, pagina, colecao)
#     payload_busca = [("id_tipo", str(payload.id_template))]
#     payload_busca += [("cp[]", v) for v in lista_cp]
#     payload_busca += [
#         ("ordem", "no_ordem"),
#         ("dt_criacao", ""),
#         ("pagina", "1"),
#         ("colecao", "S"),
#     ]

#     # 5) Executa busca
#     resp_busca = requests.post(
#         f"{BASE_URL}/documents/search",
#         data=payload_busca,
#         headers=headers
#     )
#     resp_busca.raise_for_status()
#     data = resp_busca.json()
#     if data.get("error"):
#         raise HTTPException(500, f"GED erro: {data.get('message')}")

#     # 6) Desenvelopa atributos
#     documentos_total = []
#     for doc in data.get("documents", []):
#         for attr in doc.pop("attributes", []):
#             doc[attr["name"]] = attr["value"]
#         documentos_total.append(doc)

#     # 7) Normaliza "anomes" para YYYY-MM e converte em datetime
#     datas_doc = []
#     for d in documentos_total:
#         raw = d.get(payload.campo_anomes, "")
#         # se vier 'YYYY-MM' mantém, se vier 'YYYYMM' converte
#         if len(raw) == 6 and raw.isdigit():
#             norm = f"{raw[:4]}-{raw[4:]}"
#         else:
#             norm = raw
#         try:
#             dt = datetime.strptime(norm, "%Y-%m")
#             d["_norm_anomes"] = norm
#             datas_doc.append(dt)
#         except ValueError:
#             # ignora formatos inválidos
#             continue

#     # 8) Define base como a data mais recente encontrada (ou hoje se nenhuma)
#     if datas_doc:
#         base = max(datas_doc)
#     else:
#         base = datetime.today().replace(day=1)

#     # 9) Monta janela dos últimos 6 meses a partir da base dinâmica
#     ultimos_6 = {
#         (base - relativedelta(months=i)).strftime("%Y-%m")
#         for i in range(6)
#     }

#     # 10) Filtra documentos dessa janela
#     docs_filtrados = [
#         d for d in documentos_total
#         if d.get("_norm_anomes") in ultimos_6
#     ]
#     docs_filtrados.sort(key=lambda d: d["_norm_anomes"], reverse=True)

#     # 11) Retorna resultado (FastAPI converte o dict em JSON)
#     return {
#         "total_bruto": len(documentos_total),
#         "ultimos_6_meses": sorted(ultimos_6, reverse=True),
#         "total_encontrado": len(docs_filtrados),
#         "documentos": docs_filtrados
#     }
@router.post("/documents/holerite/buscar")
def buscar_holerite(
    payload: "BuscarHolerite",
    db: Session = Depends(get_db),
):
    cpf = (payload.cpf or "").strip()
    matricula = (payload.matricula or "").strip()
    competencia = (getattr(payload, "competencia", None) or "").strip()

    # =========================
    # 1) Sem competência: só lista se existir ao menos 1 evento (cpf+matr)
    # =========================
    if not competencia:
        sql_count_evt = text("""
            SELECT COUNT(*)::int
            FROM tb_holerite_eventos e
            WHERE TRIM(e.cpf::text)      = TRIM(:cpf)
              AND TRIM(e.matricula::text) = TRIM(:matricula)
        """)
        total_evt = db.execute(sql_count_evt, {"cpf": cpf, "matricula": matricula}).scalar() or 0
        if total_evt == 0:
            raise HTTPException(
                status_code=404,
                detail="Nenhum evento encontrado para os critérios informados (cpf/matricula)."
            )

        # Lista somente competências presentes em eventos (normaliza formatos)
        sql_lista_comp = text("""
            WITH comps AS (
              SELECT DISTINCT e.competencia
              FROM tb_holerite_eventos e
              WHERE TRIM(e.cpf::text)       = TRIM(:cpf)
                AND TRIM(e.matricula::text) = TRIM(:matricula)
            )
            SELECT
              CASE
                WHEN competencia ~ '^[0-9]{4}-[0-9]{2}$' THEN SUBSTRING(competencia, 1, 4)
                WHEN competencia ~ '^[0-9]{6}$'          THEN SUBSTRING(competencia, 1, 4)
                ELSE NULL
              END::int AS ano,
              CASE
                WHEN competencia ~ '^[0-9]{4}-[0-9]{2}$' THEN SUBSTRING(competencia, 6, 2)
                WHEN competencia ~ '^[0-9]{6}$'          THEN SUBSTRING(competencia, 5, 2)
                ELSE NULL
              END::int AS mes
            FROM comps
            WHERE competencia ~ '^[0-9]{4}-[0-9]{2}$' OR competencia ~ '^[0-9]{6}$'
            ORDER BY ano DESC, mes DESC
        """)
        rows = db.execute(sql_lista_comp, {"cpf": cpf, "matricula": matricula}).fetchall()
        competencias = [{"ano": r[0], "mes": r[1]} for r in rows if r[0] is not None and r[1] is not None]
        return {"competencias": competencias}

    # =========================
    # 2) Com competência: eventos OBRIGATÓRIOS
    # =========================
    params_base = {"cpf": cpf, "matricula": matricula, "competencia": competencia}

    # filtro de competencia normalizado (YYYYMM/YYY-MM)
    filtro_comp = """
      regexp_replace(TRIM(x.competencia), '[^0-9]', '', 'g') =
      regexp_replace(TRIM(:competencia),  '[^0-9]', '', 'g')
    """

    # Pré-checagem: deve existir AO MENOS 1 evento
    sql_has_evt = text(f"""
        SELECT EXISTS(
            SELECT 1
            FROM tb_holerite_eventos x
            WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
              AND TRIM(x.matricula::text) = TRIM(:matricula)
              AND {filtro_comp}
        ) AS has_evt
    """)
    has_evt = bool(db.execute(sql_has_evt, params_base).scalar())
    if not has_evt:
        raise HTTPException(
            status_code=404,
            detail="Nenhum evento de holerite encontrado para os critérios informados."
        )

    # Eventos (garantidos)
    sql_eventos = text(f"""
        SELECT *
        FROM tb_holerite_eventos x
        WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
          AND TRIM(x.matricula::text) = TRIM(:matricula)
          AND {filtro_comp}
        ORDER BY evento
    """)
    evt_res = db.execute(sql_eventos, params_base)
    eventos = [dict(zip(evt_res.keys(), row)) for row in evt_res.fetchall()]

    # Cabeçalho (opcional)
    sql_cabecalho = text(f"""
        SELECT *
        FROM tb_holerite_cabecalhos x
        WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
          AND TRIM(x.matricula::text) = TRIM(:matricula)
          AND {filtro_comp}
        LIMIT 1
    """)
    cab_res = db.execute(sql_cabecalho, params_base)
    cab_row = cab_res.first()
    cabecalho = dict(zip(cab_res.keys(), cab_row)) if cab_row else None

    # Rodapé (opcional)
    sql_rodape = text(f"""
        SELECT *
        FROM tb_holerite_rodapes x
        WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
          AND TRIM(x.matricula::text) = TRIM(:matricula)
          AND {filtro_comp}
        LIMIT 1
    """)
    rod_res = db.execute(sql_rodape, params_base)
    rod_row = rod_res.first()
    rodape = dict(zip(rod_res.keys(), rod_row)) if rod_row else None

    return {
        "competencia_utilizada": competencia,
        "cabecalho": cabecalho,
        "eventos": eventos,   # sempre >= 1
        "rodape": rodape
    }
# ===========================================================================================================
# @router.post("/documents/search")
# def buscar_search_documentos(payload: SearchDocumentosRequest):
#     # 1) Autentica
#     try:
#         auth_key = login(
#             conta=settings.GED_CONTA, usuario=settings.GED_USUARIO, senha=settings.GED_SENHA
#         )
#     except Exception as e:
#         raise HTTPException(502, f"Falha na autenticação no GED: {e}")

#     headers = _headers(auth_key)

#     # 2) Campos do template
#     r_fields = requests.post(
#         f"{BASE_URL}/templates/getfields",
#         data={"id_template": payload.id_template},
#         headers=headers,
#         timeout=30,
#     )
#     r_fields.raise_for_status()
#     nomes_campos = [f.get("nomecampo") for f in (r_fields.json() or {}).get("fields", []) if f.get("nomecampo")]

#     if not nomes_campos:
#         raise HTTPException(400, "Template sem campos ou inválido")
#     if payload.campo_anomes not in nomes_campos:
#         raise HTTPException(400, f"Campo '{payload.campo_anomes}' não existe no template")

#     # 3) cp[] na ordem do template (sem injetar anomes)
#     lista_cp = ["" for _ in nomes_campos]
#     for item in payload.cp:
#         if item.nome not in nomes_campos:
#             raise HTTPException(400, f"Campo '{item.nome}' não existe no template")
#         lista_cp[nomes_campos.index(item.nome)] = item.valor

#     # 4) Monta conjunto de meses-alvo (YYYY-MM)
#     alvo: set[str] = set()
#     if payload.anomes:
#         n = _normaliza_anomes(payload.anomes)
#         if not n:
#             raise HTTPException(400, "anomes inválido. Use 'YYYY-MM', 'YYYYMM', 'YYYY/MM' ou 'MM/YYYY'.")
#         alvo.add(n)
#     if payload.anomes_in:
#         for val in payload.anomes_in:
#             n = _normaliza_anomes(val)
#             if not n:
#                 raise HTTPException(400, f"Valor inválido em anomes_in: '{val}'")
#             alvo.add(n)

#     if not alvo:
#         raise HTTPException(400, "Nenhum 'anomes' válido após normalização.")

#     # 5) Payload mínimo do GED
#     form = [("id_tipo", str(payload.id_template))]
#     form += [("cp[]", v) for v in lista_cp]
#     form += [
#         ("ordem", "no_ordem"),
#         ("dt_criacao", ""),
#         ("pagina", "1"),
#         ("colecao", "S"),
#     ]

#     # 6) Consulta GED
#     try:
#         r = requests.post(f"{BASE_URL}/documents/search", data=form, headers=headers, timeout=60)
#         r.raise_for_status()
#     except requests.HTTPError:
#         try:
#             raise HTTPException(r.status_code, f"GED erro: {r.json()}")
#         except Exception:
#             raise HTTPException(r.status_code, f"GED erro: {r.text}")
#     except requests.RequestException as e:
#         raise HTTPException(502, f"Falha ao consultar GED: {e}")

#     data = r.json() or {}
#     if data.get("error"):
#         raise HTTPException(500, f"GED erro: {data.get('message')}")

#     # 7) Flatten + filtro por conjunto de meses
#     documentos_total = [_flatten_attributes(doc) for doc in (data.get("documents") or [])]

#     filtrados: List[Dict[str, Any]] = []
#     for d in documentos_total:
#         bruto = str(d.get(payload.campo_anomes, "")).strip()
#         if len(bruto) == 6 and bruto.isdigit():
#             bruto = f"{bruto[:4]}-{bruto[4:]}"
#         try:
#             datetime.strptime(bruto, "%Y-%m")
#         except ValueError:
#             continue
#         if bruto in alvo:
#             d["_norm_anomes"] = bruto
#             filtrados.append(d)

#     filtrados.sort(key=lambda x: x["_norm_anomes"], reverse=True)

#     # 8) Retorno compatível (lista com todos os meses requisitados)
#     return {
#         "total_bruto": len(documentos_total),
#         "ultimos_6_meses": sorted(alvo, reverse=True),  # mantém a chave p/ não quebrar o front
#         "total_encontrado": len(filtrados),
#         "documentos": filtrados,
#     }
# # ********************************************
# @router.post("/documents/holerite/buscar")
# def buscar_holerite(
#     payload: "BuscarHolerite",
#     db: Session = Depends(get_db),
# ):
#     cpf = (payload.cpf or "").strip()
#     matricula = (payload.matricula or "").strip()
#     competencia = (getattr(payload, "competencia", None) or "").strip()

#     # =========================
#     # 1) Sem competência: só lista se existir ao menos 1 evento (cpf+matr)
#     # =========================
#     if not competencia:
#         sql_count_evt = text("""
#             SELECT COUNT(*)::int
#             FROM tb_holerite_eventos e
#             WHERE TRIM(e.cpf::text)      = TRIM(:cpf)
#               AND TRIM(e.matricula::text) = TRIM(:matricula)
#         """)
#         total_evt = db.execute(sql_count_evt, {"cpf": cpf, "matricula": matricula}).scalar() or 0
#         if total_evt == 0:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Nenhum evento encontrado para os critérios informados (cpf/matricula)."
#             )

#         # Lista somente competências presentes em eventos (normaliza formatos)
#         sql_lista_comp = text("""
#             WITH comps AS (
#               SELECT DISTINCT e.competencia
#               FROM tb_holerite_eventos e
#               WHERE TRIM(e.cpf::text)       = TRIM(:cpf)
#                 AND TRIM(e.matricula::text) = TRIM(:matricula)
#             )
#             SELECT
#               CASE
#                 WHEN competencia ~ '^[0-9]{4}-[0-9]{2}$' THEN SUBSTRING(competencia, 1, 4)
#                 WHEN competencia ~ '^[0-9]{6}$'          THEN SUBSTRING(competencia, 1, 4)
#                 ELSE NULL
#               END::int AS ano,
#               CASE
#                 WHEN competencia ~ '^[0-9]{4}-[0-9]{2}$' THEN SUBSTRING(competencia, 6, 2)
#                 WHEN competencia ~ '^[0-9]{6}$'          THEN SUBSTRING(competencia, 5, 2)
#                 ELSE NULL
#               END::int AS mes
#             FROM comps
#             WHERE competencia ~ '^[0-9]{4}-[0-9]{2}$' OR competencia ~ '^[0-9]{6}$'
#             ORDER BY ano DESC, mes DESC
#         """)
#         rows = db.execute(sql_lista_comp, {"cpf": cpf, "matricula": matricula}).fetchall()
#         competencias = [{"ano": r[0], "mes": r[1]} for r in rows if r[0] is not None and r[1] is not None]
#         return {"competencias": competencias}

#     # =========================
#     # 2) Com competência: eventos OBRIGATÓRIOS
#     # =========================
#     params_base = {"cpf": cpf, "matricula": matricula, "competencia": competencia}

#     # filtro de competencia normalizado (YYYYMM/YYY-MM)
#     filtro_comp = """
#       regexp_replace(TRIM(x.competencia), '[^0-9]', '', 'g') =
#       regexp_replace(TRIM(:competencia),  '[^0-9]', '', 'g')
#     """

#     # Pré-checagem: deve existir AO MENOS 1 evento
#     sql_has_evt = text(f"""
#         SELECT EXISTS(
#             SELECT 1
#             FROM tb_holerite_eventos x
#             WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#               AND TRIM(x.matricula::text) = TRIM(:matricula)
#               AND {filtro_comp}
#         ) AS has_evt
#     """)
#     has_evt = bool(db.execute(sql_has_evt, params_base).scalar())
#     if not has_evt:
#         raise HTTPException(
#             status_code=404,
#             detail="Nenhum evento de holerite encontrado para os critérios informados."
#         )

#     # Eventos (garantidos)
#     sql_eventos = text(f"""
#         SELECT *
#         FROM tb_holerite_eventos x
#         WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#           AND TRIM(x.matricula::text) = TRIM(:matricula)
#           AND {filtro_comp}
#         ORDER BY evento
#     """)
#     evt_res = db.execute(sql_eventos, params_base)
#     eventos = [dict(zip(evt_res.keys(), row)) for row in evt_res.fetchall()]

#     # Cabeçalho (opcional)
#     sql_cabecalho = text(f"""
#         SELECT *
#         FROM tb_holerite_cabecalhos x
#         WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#           AND TRIM(x.matricula::text) = TRIM(:matricula)
#           AND {filtro_comp}
#         LIMIT 1
#     """)
#     cab_res = db.execute(sql_cabecalho, params_base)
#     cab_row = cab_res.first()
#     cabecalho = dict(zip(cab_res.keys(), cab_row)) if cab_row else None

#     # Rodapé (opcional)
#     sql_rodape = text(f"""
#         SELECT *
#         FROM tb_holerite_rodapes x
#         WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#           AND TRIM(x.matricula::text) = TRIM(:matricula)
#           AND {filtro_comp}
#         LIMIT 1
#     """)
#     rod_res = db.execute(sql_rodape, params_base)
#     rod_row = rod_res.first()
#     rodape = dict(zip(rod_res.keys(), rod_row)) if rod_row else None

#     return {
#         "competencia_utilizada": competencia,
#         "cabecalho": cabecalho,
#         "eventos": eventos,   # sempre >= 1
#         "rodape": rodape
#     }

# ===========================================================================================================
@router.post("/documents/search")
def buscar_search_documentos(payload: SearchDocumentosRequest):
    # 1) Autentica
    try:
        auth_key = login(
            conta=settings.GED_CONTA, usuario=settings.GED_USUARIO, senha=settings.GED_SENHA
        )
    except Exception as e:
        raise HTTPException(502, f"Falha na autenticação no GED: {e}")

    headers = _headers(auth_key)

    # 2) Campos do template
    r_fields = requests.post(
        f"{BASE_URL}/templates/getfields",
        data={"id_template": payload.id_template},
        headers=headers,
        timeout=30,
    )
    r_fields.raise_for_status()
    nomes_campos = [f.get("nomecampo") for f in (r_fields.json() or {}).get("fields", []) if f.get("nomecampo")]

    if not nomes_campos:
        raise HTTPException(400, "Template sem campos ou inválido")
    if payload.campo_anomes not in nomes_campos:
        raise HTTPException(400, f"Campo '{payload.campo_anomes}' não existe no template")

    # 3) cp[] na ordem do template
    lista_cp = ["" for _ in nomes_campos]
    for item in payload.cp:
        if item.nome not in nomes_campos:
            raise HTTPException(400, f"Campo '{item.nome}' não existe no template")
        lista_cp[nomes_campos.index(item.nome)] = item.valor

    # ========= MODO LISTA DE MESES: anomes/anomes_in ausentes (ou vazios) =========
    if not payload.anomes and not payload.anomes_in:
        # Garantir que vieram tipodedoc e matricula
        try:
            tipodedoc_idx = nomes_campos.index("tipodedoc")
            tipodedoc_val = (lista_cp[tipodedoc_idx] or "").strip()
        except ValueError:
            raise HTTPException(400, "Campo 'tipodedoc' não existe no template")
        try:
            matricula_idx = nomes_campos.index("matricula")
            matricula_val = (lista_cp[matricula_idx] or "").strip()
        except ValueError:
            raise HTTPException(400, "Campo 'matricula' não existe no template")

        if not tipodedoc_val or not matricula_val:
            raise HTTPException(400, "Para listar anomes, informe 'tipodedoc' e 'matricula' em cp[].")

        # 3A) Tenta documents/filter primeiro
        form = [
            ("id_tipo", str(payload.id_template)),
            ("filtro", payload.campo_anomes),
            ("filtro1", "tipodedoc"),
            ("filtro1_valor", tipodedoc_val),
            ("filtro2", "matricula"),
            ("filtro2_valor", matricula_val),
        ]
        try:
            rf = requests.post(f"{BASE_URL}/documents/filter", data=form, headers=headers, timeout=60)
            rf.raise_for_status()
            fdata = rf.json() or {}
            if fdata.get("error"):
                raise RuntimeError(f"GED error: {fdata.get('message')}")
            grupos = fdata.get("groups") or []

            # >>> O QUE MUDOU: montar [{"ano":Y,"mes":M}, ...] a partir do retorno
            meses_set: Set[str] = set()
            for g in grupos:
                bruto = str(g.get(payload.campo_anomes, "")).strip()
                n = _normaliza_anomes(bruto)
                if n:
                    meses_set.add(n)

            if meses_set:
                meses_sorted_objs = sorted(
                    (_to_ano_mes(m) for m in meses_set),
                    key=lambda x: (x["ano"], x["mes"]),
                    reverse=True
                )
                return {"anomes": meses_sorted_objs}

            # se não retornou grupos válidos, usa fallback
        except (requests.HTTPError, requests.RequestException, RuntimeError):
            # 3B) Fallback robusto via documents/search (coleta meses "YYYY-MM")
            meses_norm = _coleta_anomes_via_search(
                headers=headers,
                id_template=payload.id_template,
                nomes_campos=nomes_campos,
                lista_cp=lista_cp,
                campo_anomes=payload.campo_anomes,
            )
            if meses_norm:
                meses_sorted_objs = sorted(
                    (_to_ano_mes(m) for m in meses_norm),
                    key=lambda x: (x["ano"], x["mes"]),
                    reverse=True
                )
                return {"anomes": meses_sorted_objs}
            raise HTTPException(404, "Nenhum mês disponível para tipodedoc/matricula informados.")

    # ========= MODO BUSCA: anomes/anomes_in presentes =========
    alvo: Set[str] = set()
    if payload.anomes:
        n = _normaliza_anomes(payload.anomes)
        if not n:
            raise HTTPException(400, "anomes inválido. Use 'YYYY-MM', 'YYYYMM', 'YYYY/MM' ou 'MM/YYYY'.")
        alvo.add(n)
    if payload.anomes_in:
        for val in payload.anomes_in:
            n = _normaliza_anomes(val)
            if not n:
                raise HTTPException(400, f"Valor inválido em anomes_in: '{val}'")
            alvo.add(n)

    form = [("id_tipo", str(payload.id_template))]
    form += [("cp[]", v) for v in lista_cp]
    form += [
        ("ordem", "no_ordem"),
        ("dt_criacao", ""),
        ("pagina", "1"),
        ("colecao", "S"),
    ]

    try:
        r = requests.post(f"{BASE_URL}/documents/search", data=form, headers=headers, timeout=60)
        r.raise_for_status()
    except requests.HTTPError:
        try:
            raise HTTPException(r.status_code, f"GED erro: {r.json()}")
        except Exception:
            raise HTTPException(r.status_code, f"GED erro: {r.text}")
    except requests.RequestException as e:
        raise HTTPException(502, f"Falha ao consultar GED (search): {e}")

    data = r.json() or {}
    if data.get("error"):
        raise HTTPException(500, f"GED erro (search): {data.get('message')}")

    documentos_total = [_flatten_attributes(doc) for doc in (data.get("documents") or [])]

    filtrados: List[Dict[str, Any]] = []
    for d in documentos_total:
        bruto = str(d.get(payload.campo_anomes, "")).strip()
        n = _normaliza_anomes(bruto)
        if n and n in alvo:
            d["_norm_anomes"] = n
            filtrados.append(d)

    if not filtrados:
        raise HTTPException(404, "Nenhum documento encontrado para os meses informados.")

    filtrados.sort(key=lambda x: x["_norm_anomes"], reverse=True)

    return {
        "total_bruto": len(documentos_total),
        "meses_solicitados": sorted(alvo, reverse=True),
        "total_encontrado": len(filtrados),
        "documentos": filtrados,
    }
# ===========================================================================================================

# @router.post("/documents/holerite/montar")
# def montar_holerite(
#     payload: MontarHolerite,
#     db: Session = Depends(get_db),
# ):
#     """
#     Monta o holerite completo (cabeçalho, eventos e rodapé)
#     com base na matrícula e competência fornecidos.
#     """
#     params = {
#         "matricula": payload.matricula,
#         "competencia": payload.competencia,
#     }

#     # 1) Cabeçalho
#     sql_cabecalho = text("""
#         SELECT empresa, filial, empresa_nome, empresa_cnpj, cliente, cliente_nome, cliente_cnpj, matricula, nome, funcao_nome, admissao, competencia, lote
#         FROM tb_holerite_cabecalhos
#         WHERE matricula   = :matricula
#           AND competencia = :competencia
#     """)
#     cab_res = db.execute(sql_cabecalho, params)
#     cab_row = cab_res.first()
#     if not cab_row:
#         raise HTTPException(
#             status_code=404,
#             detail="Cabeçalho do holerite não encontrado para a matrícula/competência informados"
#         )
#     cabecalho = dict(zip(cab_res.keys(), cab_row))

#     # 2) Eventos do holerite
#     sql_eventos = text("""
#         SELECT evento, evento_nome, referencia, valor, tipo
#         FROM tb_holerite_eventos
#         WHERE matricula   = :matricula
#           AND competencia = :competencia
#         ORDER BY evento
#     """)
#     evt_res = db.execute(sql_eventos, params)
#     evt_rows = evt_res.fetchall()
#     eventos = [dict(zip(evt_res.keys(), row)) for row in evt_rows]

#     # 3) Rodapé (totais)
#     sql_rodape = text("""
#         SELECT total_vencimentos, total_descontos, valor_liquido, salario_base, sal_contr_inss, base_calc_fgts, fgts_mes, base_calc_irrf, dep_sf, dep_irf
#         FROM tb_holerite_rodapes
#         WHERE matricula   = :matricula
#           AND competencia = :competencia
#     """)
#     rod_res = db.execute(sql_rodape, params)
#     rod_row = rod_res.first()
#     if not rod_row:
#         raise HTTPException(
#             status_code=404,
#             detail="Rodapé do holerite não encontrado para a matrícula/competência informados"
#         )
#     rodape = dict(zip(rod_res.keys(), rod_row))

    # Retorna a montagem completa
    # return {
    #     "cabecalho": cabecalho,
    #     "eventos": eventos,
    #     "rodape": rodape,
    # }

    # ——— Geração do PDF com FPDF ———
    # def pad_left6(valor: str) -> str:
    #     v = str(valor).strip()
    #     if len(v) < 6:
    #         v = v.zfill(6)
    #     return v.zfill(6)

    # cabecalho["matricula"] = pad_left6(cabecalho["matricula"])

    # def pad_left5(valor: str) -> str:
    #     v = str(valor).strip()
    #     if len(v) < 5:
    #         v = v.zfill(5)
    #     return v.zfill(5)

    # cabecalho["cliente"] = pad_left5(cabecalho["cliente"])

    # def pad_left3(valor: str) -> str:
    #     v = str(valor).strip()
    #     if len(v) < 3:
    #         v = v.zfill(3)
    #     return v.zfill(3)

    # cabecalho["empresa"] = pad_left3(cabecalho["empresa"])
    # cabecalho["filial"]  = pad_left3(cabecalho["filial"])

    # def formatar_admissao(iso: str) -> str:
    #     dt = datetime.fromisoformat(iso)
    #     return format_date(dt, format="dd/MM/yyyy", locale="pt_BR")

    # def formatar_competencia(yyyymm: str) -> str:
    #     dt = datetime.strptime(yyyymm, "%Y%m")
    #     return format_date(dt, format="LLLL/yyyy", locale="pt_BR").capitalize()

    # cabecalho["admissao"] = formatar_admissao(cabecalho["admissao"])
    # cabecalho["competencia"] = formatar_competencia(cabecalho["competencia"])

    # pdf = FPDF(format='A4', unit='mm')
    # pdf.add_page()
    # pdf.set_auto_page_break(auto=True, margin=15)

    # pdf.ln(5)
    # pdf.set_font("Arial", style='B', size=12)
    # pdf.cell(0, 8, f"Recibo de Pagamento de Salário", ln=1)
    # pdf.set_font("Arial", size=10)

    # pdf.cell(0, 8, f"Empresa: {cabecalho.get('empresa')}", ln=1)
    # pdf.cell(0, 8, f"{cabecalho.get('filial')}", ln=1)
    # pdf.cell(0, 8, f"{cabecalho.get('empresa_nome')}", ln=1)
    # pdf.cell(0, 8, f"Nº Inscrição: {cabecalho.get('empresa_cnpj')}", ln=1)
    # pdf.cell(0, 8, f"Cliente: {cabecalho['cliente']}", ln=1)
    # pdf.cell(0, 8, f"{cabecalho.get('cliente_nome')}", ln=1)
    # pdf.cell(0, 8, f"Nº Inscrição: {cabecalho.get('cliente_cnpj')}", ln=1)
    # pdf.cell(0, 8, f"Código: {cabecalho['matricula']}", ln=1)
    # pdf.cell(0, 8, f"Nome do Funcionário: {cabecalho.get('nome')}", ln=1)
    # pdf.cell(0, 8, f"Função: {cabecalho.get('funcao_nome')}", ln=1)
    # pdf.cell(0, 8, f"Admissão: {cabecalho['admissao']}", ln=1)
    # pdf.cell(0, 8, f"Competência: {cabecalho['competencia']}", ln=1)
    # pdf.cell(0, 8, f"Lote: {cabecalho.get('lote')}", ln=1)

    # pdf.ln(5)
    # pdf.set_font("Arial", style='B', size=12)
    # pdf.cell(0, 8, "Eventos:", ln=1)
    # pdf.set_font("Arial", size=10)
    # for evt in eventos:
    #     cod_evnt = evt.get("evento", "")
    #     nome = evt.get("evento_nome", str(evt.get("evento", "")))
    #     val  = evt.get("valor", "")
    #     tipo = evt.get("tipo", "")
    #     pdf.cell(0, 8, f"{cod_evnt} {nome}: {val} | Tipo: {tipo}", ln=1)

    # def pad_left2(valor: str) -> str:
    #     v = str(valor).strip()
    #     if len(v) < 2:
    #         v = v.zfill(2)
    #     return v.zfill(2)

    # rodape["dep_sf"] = pad_left2(rodape["dep_sf"])
    # rodape["dep_irf"] = pad_left2(rodape["dep_irf"])

    # pdf.ln(5)
    # pdf.set_font("Arial", style='B', size=12)
    # pdf.cell(0, 8, "Totais:", ln=1)
    # pdf.set_font("Arial", size=10)
    # pdf.cell(0, 8, f"Total Vencimentos: {rodape.get('total_vencimentos')}", ln=1)
    # pdf.cell(0, 8, f"Total Descontos: {rodape.get('total_descontos')}", ln=1)
    # pdf.cell(0, 8, f"Valor Líquido: {rodape.get('valor_liquido')}", ln=1)
    # pdf.cell(0, 8, f"Salário Base: {rodape.get('salario_base')}/M", ln=1)
    # pdf.cell(0, 8, f"Sal. Contr. INSS: {rodape.get('sal_contr_inss')}", ln=1)
    # pdf.cell(0, 8, f"Base Cálc FGTS: {rodape.get('base_calc_fgts')}", ln=1)
    # pdf.cell(0, 8, f"F.G.T.S. do Mês: {rodape.get('fgts_mes')}", ln=1)
    # pdf.cell(0, 8, f"Base Cálc IRRF: {rodape.get('base_calc_irrf')}", ln=1)
    # pdf.cell(0, 8, f"DEP SF: {rodape['dep_sf']}", ln=1)
    # pdf.cell(0, 8, f"DEP IRF: {rodape['dep_irf']}", ln=1)

    # # ——— Correção: dest='S' retorna bytearray, não string ———
    # raw_pdf = pdf.output(dest='S')         # → retorna bytearray
    # pdf_bytes = bytes(raw_pdf)             # → converte para bytes
    # base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')  # codifica em base64

    # return {
    #     "cabecalho": cabecalho,
    #      "eventos": eventos,
    #      "rodape": rodape,
    #      "pdf_base64": base64_pdf
    # }

def pad_left(valor: str, width: int) -> str:
    return str(valor).strip().zfill(width)

def fmt_num(valor: float) -> str:
    s = f"{valor:,.2f}"        # "12,345.60"
    s = s.replace(",", "X").replace(".", ",")  # "12X345,60"
    return s.replace("X", ".")  # "12.345,60"

def truncate(text: str, max_len: int) -> str:
    text = text or ""
    return text if len(text) <= max_len else text[: max_len - 3] + "..."

def gerar_recibo(cabecalho: dict, eventos: list[dict], rodape: dict, page_number: int = 1) -> bytes:
    # 1) Padding
    cabecalho["matricula"] = pad_left(cabecalho["matricula"], 6)
    cabecalho["cliente"]   = pad_left(cabecalho["cliente"],   5)
    cabecalho["empresa"]   = pad_left(cabecalho["empresa"],   3)
    cabecalho["filial"]    = pad_left(cabecalho["filial"],    3)

    # 2) Formata datas
    adm = datetime.fromisoformat(cabecalho["admissao"])
    cabecalho["admissao"]   = format_date(adm, "dd/MM/yyyy", locale="pt_BR")
    comp = datetime.strptime(cabecalho["competencia"], "%Y%m")
    cabecalho["competencia"] = format_date(comp, "LLLL/yyyy", locale="pt_BR").capitalize()

    # Truncamento limitado
    empresa_nome = truncate(cabecalho.get("empresa_nome", ""), 50)
    cliente_nome = truncate(cabecalho.get("cliente_nome", ""), 50)
    funcionario  = truncate(cabecalho.get("nome", ""), 30)
    funcao       = truncate(cabecalho.get("funcao_nome", ""), 16)

    # 3) Inicializa PDF
    pdf = FPDF(format='A4', unit='mm')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # — Cabeçalho Superior —
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 6, "Recibo de Pagamento de Salário", ln=0)
    pdf.ln(6)

    # — Empresa e Cliente —
    pdf.set_font("Arial", '', 9)
    pdf.cell(120, 5, f"Empresa: {cabecalho['empresa']} - {cabecalho['filial']} {empresa_nome}", ln=0)
    pdf.cell(0,   5, f"Nº Inscrição: {cabecalho['empresa_cnpj']}", ln=1, align='R')
    pdf.cell(120, 5, f"Cliente: {cabecalho['cliente']} {cliente_nome}",       ln=0)
    pdf.cell(0,   5, f"Nº Inscrição: {cabecalho['cliente_cnpj']}", ln=1, align='R')
    pdf.ln(3)

    # — Campos do Funcionário —
    col_widths = [20, 60, 40, 30, 30]
    headers    = ["Código", "Nome do Funcionário", "Função", "Admissão", "Competência"]
    pdf.set_font("Arial", 'B', 9)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 6, h)
    pdf.ln(6)

    pdf.set_font("Arial", '', 7)
    vals = [cabecalho["matricula"], funcionario, funcao,
            cabecalho["admissao"], cabecalho["competencia"]]
    for w, v in zip(col_widths, vals):
        pdf.cell(w, 6, v)
    pdf.ln(6)

    # — Linha separando cabeçalho de eventos —
    y_sep = pdf.get_y()
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, y_sep, pdf.w - pdf.r_margin, y_sep)
    pdf.ln(3)

    # — Tabela de Eventos com cabeçalhos centralizados nas colunas numéricas —
    evt_headers = ["Cód.", "Descrição", "Referência", "Vencimentos", "Descontos"]
    pdf.set_font("Arial", 'B', 9)
    for i, (w, h) in enumerate(zip(col_widths, evt_headers)):
        align = 'C' if i >= 2 else ''
        pdf.cell(w, 6, h, align=align)
    pdf.ln(6)

    # — Dados de Eventos, truncando e convertendo para maiúsculas —
    y_start = pdf.get_y()
    pdf.set_font("Arial", '', 9)
    for evt in eventos:
        nome_evt = truncate(evt.get("evento_nome", ""), 30).upper()
        row = [
            str(evt['evento']),
            nome_evt,
            fmt_num(evt['referencia']),
            fmt_num(evt['valor']) if evt['tipo'] == 'V' else "",
            fmt_num(evt['valor']) if evt['tipo'] == 'D' else ""
        ]
        for i, (w, v) in enumerate(zip(col_widths, row)):
            align = 'R' if i >= 2 else ''
            pdf.cell(w, 6, v, align=align)
        pdf.ln(6)
    y_end = pdf.get_y()

    # — Linhas verticais internas —
    x0 = pdf.l_margin + col_widths[0] + col_widths[1]
    x1 = x0 + col_widths[2]
    x2 = x1 + col_widths[3]
    pdf.set_line_width(0.2)
    for x in (x0, x1, x2):
        pdf.line(x, y_start, x, y_end)
    pdf.ln(2)

    # — Linha separando eventos do rodapé —
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)

    # — Totais lado a lado —
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    half   = (usable - 10) / 2
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(half, 6, "Total Vencimentos", ln=0, align='R')
    pdf.cell(10,   6, "", ln=0)
    pdf.cell(half, 6, "Total Descontos",    ln=1, align='R')
    pdf.set_font("Arial", '', 9)
    pdf.cell(half, 6, fmt_num(rodape['total_vencimentos']), ln=0, align='R')
    pdf.cell(10,   6, "", ln=0)
    pdf.cell(half, 6, fmt_num(rodape['total_descontos']),    ln=1, align='R')
    pdf.ln(3)

    # — Valor Líquido —
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(0, 6, f"Valor Líquido »» {fmt_num(rodape['valor_liquido'])}", ln=1, align='R')
    pdf.ln(4)

    # — Linha antes do rodapé detalhado —
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)

    # — Rodapé Detalhado —
    detalhes = ["Salário Base", "Sal. Contr. INSS", "Base Cálc FGTS",
               "F.G.T.S. do Mês", "Base Cálc IRRF", "DEP SF", "DEP IRF"]
    pdf.set_font("Arial", 'B', 8)
    for d in detalhes:
        pdf.cell(28, 5, d)
    pdf.ln(5)

    pdf.set_font("Arial", '', 8)
    footer_vals = [
        f"{fmt_num(rodape['salario_base'])}/M",
        fmt_num(rodape['sal_contr_inss']),
        fmt_num(rodape['base_calc_fgts']),
        fmt_num(rodape['fgts_mes']),
        fmt_num(rodape['base_calc_irrf']),
        pad_left(rodape['dep_sf'], 2),
        pad_left(rodape['dep_irf'], 2),
    ]
    for v in footer_vals:
        pdf.cell(28, 6, v)
    pdf.ln(10)

    # — Assinatura e Data —
    pdf.ln(10)
    y_sig = pdf.get_y()
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, y_sig, pdf.l_margin + 80, y_sig)
    pdf.ln(2)
    pdf.set_font("Arial", '', 9)
    pdf.cell(80, 6, funcionario, ln=0)
    pdf.cell(0, 6, "Data: ____/____/____", ln=1, align='R')

    return pdf.output(dest='S').encode('latin-1')

@router.post("/documents/holerite/montar")
def montar_holerite(
    payload: MontarHolerite,
    db: Session = Depends(get_db)
):
    params = {"matricula": payload.matricula, "competencia": payload.competencia, "lote": payload.lote, "cpf": payload.cpf}

    # Cabeçalho
    sql_cabecalho = text("""
        SELECT empresa, filial, empresa_nome, empresa_cnpj,
               cliente, cliente_nome, cliente_cnpj,
               matricula, nome, funcao_nome, admissao,
               competencia, lote
        FROM tb_holerite_cabecalhos
        WHERE matricula   = :matricula
          AND competencia = :competencia
          AND lote = :lote
          AND cpf = :cpf
    """)
    cab_res = db.execute(sql_cabecalho, params)
    cab_row = cab_res.first()
    if not cab_row:
        raise HTTPException(status_code=404, detail="Cabeçalho não encontrado")
    cabecalho = dict(zip(cab_res.keys(), cab_row))

    # Eventos
    sql_eventos = text("""
        SELECT evento, evento_nome, referencia, valor, tipo
        FROM tb_holerite_eventos
        WHERE matricula   = :matricula
          AND competencia = :competencia
          AND cpf = :cpf
        ORDER BY evento
    """)
    evt_res = db.execute(sql_eventos, params)
    eventos = [dict(zip(evt_res.keys(), row)) for row in evt_res.fetchall()]

    if not eventos:
      return Response(status_code=204)

    # Validação de tipo de eventos (V ou D)
    for evt in eventos:
        tipo = evt.get('tipo', '').upper()
        if tipo not in ('V', 'D'):
            raise HTTPException(status_code=400, detail=f"Tipo de evento inválido: {tipo}")
        evt['tipo'] = tipo

    # Rodapé
    sql_rodape = text("""
        SELECT total_vencimentos, total_descontos,
               valor_liquido, salario_base,
               sal_contr_inss, base_calc_fgts,
               fgts_mes, base_calc_irrf,
               dep_sf, dep_irf
        FROM tb_holerite_rodapes
        WHERE matricula   = :matricula
          AND competencia = :competencia
          AND cpf = :cpf
    """)
    rod_res = db.execute(sql_rodape, params)
    rod_row = rod_res.first()
    if not rod_row:
        raise HTTPException(status_code=404, detail="Rodapé não encontrado")
    rodape = dict(zip(rod_res.keys(), rod_row))

    # Gera PDF e retorna base64
    raw_pdf = gerar_recibo(cabecalho, eventos, rodape)
    pdf_base64 = base64.b64encode(raw_pdf).decode("utf-8")

    return {
        "cabecalho": cabecalho,
        "eventos": eventos,
        "rodape": rodape,
        "pdf_base64": pdf_base64
    }



# ********************************************

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