from fastapi import APIRouter, HTTPException, Form, Depends, Response, Body
from typing import Any, Dict, Optional, Set
import requests
from pydantic import BaseModel, Field, field_validator
from pydantic import ConfigDict
from datetime import datetime
from babel.dates import format_date
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.connection import get_db
from config.settings import settings
from typing import List
import base64
from fpdf import FPDF

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
    anomes: Optional[str] = None
    anomes_in: Optional[List[str]] = None

    @field_validator("campo_anomes")
    @classmethod
    def _valida_campo_anomes(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("campo_anomes é obrigatório")
        return v

    @field_validator("anomes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

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

# class BuscarHolerite(BaseModel):
#     cpf: str = Field(..., min_length=11, max_length=14, description="CPF sem formatação, 11 dígitos")
#     matricula: str
#     competencia: str

class BuscarHolerite(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Pydantic v2
    cpf: str = Field(..., min_length=1)
    matricula: Optional[str] = None
    competencia: Optional[str] = None
    empresa: Optional[str] = None        # código do cliente (do cabeçalho)
    cliente_nome: Optional[str] = None   # nome da empresa (do cabeçalho)

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
    if len(v) == 6 and v.isdigit():
        return f"{v[:4]}-{v[4:]}"
    if "/" in v:
        a, b = v.split("/", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
        if len(b) == 4 and a.isdigit():
            return f"{b}-{a.zfill(2)}"
    if "-" in v:
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
        partes = s.split("-")
        if len(partes) >= 2:
            ano = int(partes[0])
            mes = partes[1][:2].zfill(2)
            return ano, mes
        s = "".join(partes)
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
    if len(v) == 6 and v.isdigit():
        return f"{v[:4]}-{v[4:]}"
    if "/" in v:
        a, b = v.split("/", 1)
        if len(a) == 4 and b.isdigit():
            return f"{a}-{b.zfill(2)}"
        if len(b) == 4 and a.isdigit():
            return f"{b}-{a.zfill(2)}"
    if "-" in v:
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
        form += [("cp[]", v) for v in lista_cp]
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
    auth_key = login(
        conta=settings.GED_CONTA,
        usuario=settings.GED_USUARIO,
        senha=settings.GED_SENHA
    )

    headers = {
        "Authorization": auth_key,
        "Content-Type": "application/x-www-form-urlencoded; charset=ISO-8859-1"
    }

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

    for campo in payload.campos:
        if campo.nome not in nomes_campos:
            raise HTTPException(status_code=400, detail=f"Campo '{campo.nome}' não encontrado no template")
        idx = nomes_campos.index(campo.nome)
        lista_cp[idx] = campo.valor

    data = {
        "id_tipo": str(payload.id_tipo),
        "formato": payload.formato,
        "documento_nome": payload.documento_nome,
        "documento": payload.documento_base64
    }
    for valor in lista_cp:
        data.setdefault("cp[]", []).append(valor)

    response = requests.post(
        f"{BASE_URL}/documents/uploadbase64",
        headers=headers,
        data=data
    )

    try:
        return response.json()
    except Exception:
        raise HTTPException(status_code=500, detail=f"Erro no upload: {response.text}")

# @router.post("/documents/holerite/buscar")
# def buscar_holerite(
#     payload: "BuscarHolerite",
#     db: Session = Depends(get_db),
# ):
#     cpf = (payload.cpf or "").strip()
#     matricula = (payload.matricula or "").strip()
#     competencia = (getattr(payload, "competencia", None) or "").strip()

#     if not competencia:
#         sql_lista_comp = text("""
#             WITH norm_evt AS (
#                 SELECT DISTINCT
#                        regexp_replace(TRIM(e.competencia), '[^0-9]', '', 'g') AS comp,
#                        e.lote
#                 FROM tb_holerite_eventos e
#                 WHERE TRIM(e.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(e.matricula::text) = TRIM(:matricula)
#                   AND e.competencia IS NOT NULL
#             ),
#             norm_cab AS (
#                 SELECT DISTINCT
#                        regexp_replace(TRIM(c.competencia), '[^0-9]', '', 'g') AS comp,
#                        c.lote
#                 FROM tb_holerite_cabecalhos c
#                 WHERE TRIM(c.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(c.matricula::text) = TRIM(:matricula)
#                   AND c.competencia IS NOT NULL
#             ),
#             norm_rod AS (
#                 SELECT DISTINCT
#                        regexp_replace(TRIM(r.competencia), '[^0-9]', '', 'g') AS comp,
#                        r.lote
#                 FROM tb_holerite_rodapes r
#                 WHERE TRIM(r.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(r.matricula::text) = TRIM(:matricula)
#                   AND r.competencia IS NOT NULL
#             ),
#             valid AS (
#                 SELECT e.comp
#                 FROM norm_evt e
#                 JOIN norm_cab c ON c.comp = e.comp AND c.lote = e.lote
#                 JOIN norm_rod r ON r.comp = e.comp AND r.lote = e.lote
#                 GROUP BY e.comp
#             )
#             SELECT
#               CAST(SUBSTRING(comp, 1, 4) AS int) AS ano,
#               CAST(SUBSTRING(comp, 5, 2) AS int) AS mes
#             FROM valid
#             WHERE comp ~ '^[0-9]{6}$'
#             ORDER BY ano DESC, mes DESC
#         """)
#         rows = db.execute(sql_lista_comp, {"cpf": cpf, "matricula": matricula}).fetchall()
#         competencias = [{"ano": r[0], "mes": r[1]} for r in rows if r[0] is not None and r[1] is not None]

#         if not competencias:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Nenhuma competência disponível com eventos, cabeçalho e rodapé no mesmo lote."
#             )

#         return {"competencias": competencias}

#     params_base = {"cpf": cpf, "matricula": matricula, "competencia": competencia}

#     filtro_comp = """
#       regexp_replace(TRIM(x.competencia), '[^0-9]', '', 'g') =
#       regexp_replace(TRIM(:competencia),  '[^0-9]', '', 'g')
#     """

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
#     if not eventos:
#         raise HTTPException(status_code=404, detail="Nenhum evento encontrado após a consulta.")

#     lotes = sorted({e.get("lote") for e in eventos if e.get("lote") is not None}, reverse=True)

#     cabecalho = None
#     rodape = None
#     lote_escolhido = None

#     for lote in lotes or [None]:
#         params_try = dict(params_base)
#         if lote is not None:
#             params_try["lote"] = lote

#         if lote is not None:
#             sql_cab = text(f"""
#                 SELECT *
#                 FROM tb_holerite_cabecalhos x
#                 WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(x.matricula::text) = TRIM(:matricula)
#                   AND {filtro_comp}
#                   AND x.lote = :lote
#                 LIMIT 1
#             """)
#         else:
#             sql_cab = text(f"""
#                 SELECT *
#                 FROM tb_holerite_cabecalhos x
#                 WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(x.matricula::text) = TRIM(:matricula)
#                   AND {filtro_comp}
#                 ORDER BY lote DESC NULLS LAST
#                 LIMIT 1
#             """)

#         cab_res = db.execute(sql_cab, params_try)
#         cab_row = cab_res.first()
#         cab_tmp = dict(zip(cab_res.keys(), cab_row)) if cab_row else None

#         if lote is not None:
#             sql_rod = text(f"""
#                 SELECT *
#                 FROM tb_holerite_rodapes x
#                 WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(x.matricula::text) = TRIM(:matricula)
#                   AND {filtro_comp}
#                   AND x.lote = :lote
#                 LIMIT 1
#             """)
#         else:
#             sql_rod = text(f"""
#                 SELECT *
#                 FROM tb_holerite_rodapes x
#                 WHERE TRIM(x.cpf::text)       = TRIM(:cpf)
#                   AND TRIM(x.matricula::text) = TRIM(:matricula)
#                   AND {filtro_comp}
#                 ORDER BY lote DESC NULLS LAST
#                 LIMIT 1
#             """)

#         rod_res = db.execute(sql_rod, params_try)
#         rod_row = rod_res.first()
#         rod_tmp = dict(zip(rod_res.keys(), rod_row)) if rod_row else None

#         if cab_tmp and rod_tmp:
#             cabecalho = cab_tmp
#             rodape = rod_tmp
#             lote_escolhido = lote
#             break

#     if not cabecalho and not rodape:
#         raise HTTPException(
#             status_code=404,
#             detail="Cabeçalho e rodapé ausentes para a competência informada (possível divergência de lote)."
#         )
#     if not cabecalho:
#         raise HTTPException(status_code=404, detail="Cabeçalho ausente para a competência/lote informados.")
#     if not rodape:
#         raise HTTPException(status_code=404, detail="Rodapé ausente para a competência/lote informados.")

#     if lote_escolhido is not None:
#         eventos = [e for e in eventos if e.get("lote") == lote_escolhido]
#         if not eventos:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Eventos não encontrados para o mesmo lote do cabeçalho/rodapé."
#             )

#     return {
#         "competencia_utilizada": competencia,
#         "cabecalho": cabecalho,
#         "eventos": eventos,
#         "rodape": rodape
#     }

@router.post("/documents/holerite/buscar")
def buscar_holerite(
    payload: BuscarHolerite = Body(...),
    db: Session = Depends(get_db),
):
    cpf = (payload.cpf or "").strip()
    matricula = (payload.matricula or "").strip() if payload.matricula else ""
    competencia = (payload.competencia or "").strip() if payload.competencia else ""
    empresa = (payload.empresa or None)
    cliente_nome = (payload.cliente_nome or None)

    if not cpf:
        raise HTTPException(status_code=422, detail="Informe cpf.")

    # Filtros dinâmicos
    params: Dict[str, Any] = {"cpf": cpf}
    f_evt = ""  # eventos
    f_cab = ""  # cabeçalhos (empresa/cliente_nome só aqui)
    f_rod = ""  # rodapés

    if matricula:
        f_evt += " AND TRIM(e.matricula::text) = TRIM(:matricula) "
        f_cab += " AND TRIM(c.matricula::text) = TRIM(:matricula) "
        f_rod += " AND TRIM(r.matricula::text) = TRIM(:matricula) "
        params["matricula"] = matricula

    if empresa:
        f_cab += " AND TRIM(c.cliente::text) = TRIM(:empresa) "
        params["empresa"] = str(empresa).strip()

    if cliente_nome:
        f_cab += " AND TRIM(c.cliente_nome) = TRIM(:cliente_nome) "
        params["cliente_nome"] = cliente_nome.strip()

    filtro_comp_evt = """
      regexp_replace(TRIM(e.competencia), '[^0-9]', '', 'g') =
      regexp_replace(TRIM(:competencia),  '[^0-9]', '', 'g')
    """
    filtro_comp_cab = filtro_comp_evt.replace("e.", "c.")
    filtro_comp_rod = filtro_comp_evt.replace("e.", "r.")

    # =========================================================
    # 1) Sem competencia e sem empresa -> listar EMPRESAS por CPF
    # =========================================================
    if not competencia and not empresa and not cliente_nome:
        sql_empresas = text(f"""
            WITH norm_evt AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(e.competencia), '[^0-9]', '', 'g') AS comp,
                       e.lote, e.matricula
                FROM tb_holerite_eventos e
                WHERE TRIM(e.cpf::text) = TRIM(:cpf)
                  AND e.competencia IS NOT NULL
            ),
            norm_cab AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(c.competencia), '[^0-9]', '', 'g') AS comp,
                       c.lote, c.matricula, c.cliente, c.cliente_nome
                FROM tb_holerite_cabecalhos c
                WHERE TRIM(c.cpf::text) = TRIM(:cpf)
                  AND c.competencia IS NOT NULL
            ),
            norm_rod AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(r.competencia), '[^0-9]', '', 'g') AS comp,
                       r.lote, r.matricula
                FROM tb_holerite_rodapes r
                WHERE TRIM(r.cpf::text) = TRIM(:cpf)
                  AND r.competencia IS NOT NULL
            ),
            valid AS (
                SELECT c.cliente, c.cliente_nome
                FROM norm_evt e
                JOIN norm_cab c ON c.comp = e.comp AND c.lote = e.lote AND c.matricula = e.matricula
                JOIN norm_rod r ON r.comp = e.comp AND r.lote = e.lote AND r.matricula = e.matricula
                GROUP BY c.cliente, c.cliente_nome
            )
            SELECT DISTINCT cliente, cliente_nome
            FROM valid
            ORDER BY cliente_nome NULLS LAST, cliente
        """)
        rows = db.execute(sql_empresas, {"cpf": cpf}).fetchall()
        empresas = [{"cliente": str(r[0]) if r[0] is not None else None,
                     "cliente_nome": r[1]} for r in rows]
        if not empresas:
            raise HTTPException(status_code=404, detail="Nenhuma empresa vinculada encontrada para o CPF.")
        return {"tipo": "empresas", "empresas": empresas}

    # =========================================================
    # 2) COM EMPRESA e SEM COMPETÊNCIA
    #    -> **Exigir chave composta**: CPF + MATRÍCULA
    #       Se a matrícula não vier, resolver primeiro.
    # =========================================================
    if not competencia and (empresa or cliente_nome):
        # Se matrícula não veio: descobrir todas as matrículas do CPF para essa empresa (no CABEÇALHO)
        if not matricula:
            sql_mats_empresa = text(f"""
                SELECT DISTINCT TRIM(c.matricula::text) AS matricula, MAX(TRIM(c.cliente_nome)) AS cliente_nome
                FROM tb_holerite_cabecalhos c
                WHERE TRIM(c.cpf::text) = TRIM(:cpf)
                  {f_cab}  -- já inclui cliente/cliente_nome se informados
                  AND c.matricula IS NOT NULL AND TRIM(c.matricula::text) <> ''
                GROUP BY TRIM(c.matricula::text)
                ORDER BY 1
            """)
            mats_rows = db.execute(sql_mats_empresa, params).fetchall()
            mats = [r[0] for r in mats_rows]

            if len(mats) == 0:
                raise HTTPException(status_code=404, detail="Nenhuma matrícula encontrada para o CPF/empresa.")
            if len(mats) > 1:
                # 409: o front deve escolher a matrícula
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Mais de uma matrícula encontrada para a empresa. Informe o campo 'matricula'.",
                        "matriculas": mats
                    }
                )

            # ÚNICA matrícula → aplicar e seguir
            matricula = mats[0]
            params["matricula"] = matricula
            f_evt += " AND TRIM(e.matricula::text) = TRIM(:matricula) "
            f_cab += " AND TRIM(c.matricula::text) = TRIM(:matricula) "
            f_rod += " AND TRIM(r.matricula::text) = TRIM(:matricula) "

        # Agora há empresa + matrícula → listar competências dessa chave (cpf+empresa+matricula)
        sql_lista_comp = text(f"""
            WITH norm_evt AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(e.competencia), '[^0-9]', '', 'g') AS comp,
                       e.lote
                FROM tb_holerite_eventos e
                WHERE TRIM(e.cpf::text) = TRIM(:cpf)
                  AND e.competencia IS NOT NULL
                  {f_evt}    -- filtra por matrícula
            ),
            norm_cab AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(c.competencia), '[^0-9]', '', 'g') AS comp,
                       c.lote, MAX(c.cliente_nome) OVER () AS cliente_nome
                FROM tb_holerite_cabecalhos c
                WHERE TRIM(c.cpf::text) = TRIM(:cpf)
                  AND c.competencia IS NOT NULL
                  {f_cab}    -- filtra por empresa + matrícula
            ),
            norm_rod AS (
                SELECT DISTINCT
                       regexp_replace(TRIM(r.competencia), '[^0-9]', '', 'g') AS comp,
                       r.lote
                FROM tb_holerite_rodapes r
                WHERE TRIM(r.cpf::text) = TRIM(:cpf)
                  AND r.competencia IS NOT NULL
                  {f_rod}    -- filtra por matrícula
            ),
            valid AS (
                SELECT e.comp, (SELECT MAX(c2.cliente_nome) FROM norm_cab c2) AS cliente_nome
                FROM norm_evt e
                JOIN norm_cab c ON c.comp = e.comp AND c.lote = e.lote
                JOIN norm_rod r ON r.comp = e.comp AND r.lote = e.lote
                GROUP BY e.comp
            )
            SELECT
              (SELECT cliente_nome FROM valid v2 LIMIT 1) AS cliente_nome,
              CAST(SUBSTRING(comp, 1, 4) AS int) AS ano,
              CAST(SUBSTRING(comp, 5, 2) AS int) AS mes
            FROM valid
            WHERE comp ~ '^[0-9]{{6}}$'
            ORDER BY ano DESC, mes DESC
        """)
        rows = db.execute(sql_lista_comp, params).fetchall()
        competencias = [{"ano": r[1], "mes": r[2]} for r in rows if r[1] is not None and r[2] is not None]
        if not competencias:
            raise HTTPException(status_code=404, detail="Nenhuma competência disponível para CPF/empresa/matrícula informados.")

        # Captura o cliente_nome se disponível via consulta; se não, mantém o que veio
        cliente_nome_out = rows[0][0] if rows and rows[0][0] is not None else cliente_nome

        return {
            "tipo": "competencias",
            "empresa": empresa,
            "cliente_nome": cliente_nome_out,
            "matricula": matricula,
            "competencias": competencias
        }

    # =========================================================
    # 3) COMPETÊNCIA informada
    #    (se matricula não veio, inferir única respeitando filtros de empresa/cliente_nome no CABEÇALHO)
    # =========================================================
    if competencia and not matricula:
        params_comp = dict(params)
        params_comp["competencia"] = competencia
        sql_mats = text(f"""
            SELECT DISTINCT c.matricula
            FROM tb_holerite_cabecalhos c
            WHERE TRIM(c.cpf::text) = TRIM(:cpf)
              AND {filtro_comp_cab}
              {f_cab}      -- empresa/cliente_nome só aqui
        """)
        mats = [str(r[0]) for r in db.execute(sql_mats, params_comp).fetchall() if r[0] is not None]
        if len(mats) == 0:
            raise HTTPException(status_code=404, detail="Nenhum registro encontrado para a competência informada.")
        if len(mats) > 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Mais de uma matrícula encontrada para a competência. Informe o campo 'matricula'.",
                    "matriculas": mats
                }
            )
        matricula = mats[0]
        params["matricula"] = matricula
        f_evt += " AND TRIM(e.matricula::text) = TRIM(:matricula) "
        f_cab += " AND TRIM(c.matricula::text) = TRIM(:matricula) "
        f_rod += " AND TRIM(r.matricula::text) = TRIM(:matricula) "

    # A partir daqui temos competencia e (possivelmente) matricula
    params_base = dict(params)
    params_base["competencia"] = competencia

    # 3.1 Verifica eventos
    sql_has_evt = text(f"""
        SELECT EXISTS(
            SELECT 1
            FROM tb_holerite_eventos e
            WHERE TRIM(e.cpf::text) = TRIM(:cpf)
              AND {filtro_comp_evt}
              {f_evt}
        ) AS has_evt
    """)
    has_evt = bool(db.execute(sql_has_evt, params_base).scalar())
    if not has_evt:
        raise HTTPException(status_code=404, detail="Nenhum evento de holerite encontrado para os critérios informados.")

    # 3.2 Busca eventos
    sql_eventos = text(f"""
        SELECT *
        FROM tb_holerite_eventos e
        WHERE TRIM(e.cpf::text) = TRIM(:cpf)
          AND {filtro_comp_evt}
          {f_evt}
        ORDER BY evento
    """)
    evt_res = db.execute(sql_eventos, params_base)
    eventos = [dict(zip(evt_res.keys(), row)) for row in evt_res.fetchall()]
    if not eventos:
        raise HTTPException(status_code=404, detail="Nenhum evento encontrado após a consulta.")

    # 3.3 Alinha por lote
    lotes = sorted({e.get("lote") for e in eventos if e.get("lote") is not None}, reverse=True)

    cabecalho = None
    rodape = None
    lote_escolhido = None

    for lote in lotes or [None]:
        params_try = dict(params_base)
        if lote is not None:
            params_try["lote"] = lote

        # CABEÇALHO (aplica empresa/cliente_nome + matricula)
        if lote is not None:
            sql_cab = text(f"""
                SELECT *
                FROM tb_holerite_cabecalhos c
                WHERE TRIM(c.cpf::text) = TRIM(:cpf)
                  AND {filtro_comp_cab}
                  {f_cab}
                  AND c.lote = :lote
                LIMIT 1
            """)
        else:
            sql_cab = text(f"""
                SELECT *
                FROM tb_holerite_cabecalhos c
                WHERE TRIM(c.cpf::text) = TRIM(:cpf)
                  AND {filtro_comp_cab}
                  {f_cab}
                ORDER BY lote DESC NULLS LAST
                LIMIT 1
            """)

        cab_res = db.execute(sql_cab, params_try)
        cab_row = cab_res.first()
        cab_tmp = dict(zip(cab_res.keys(), cab_row)) if cab_row else None

        # RODAPÉ (apenas cpf+matricula+comp+lote)
        if lote is not None:
            sql_rod = text(f"""
                SELECT *
                FROM tb_holerite_rodapes r
                WHERE TRIM(r.cpf::text) = TRIM(:cpf)
                  AND {filtro_comp_rod}
                  {f_rod}
                  AND r.lote = :lote
                LIMIT 1
            """)
        else:
            sql_rod = text(f"""
                SELECT *
                FROM tb_holerite_rodapes r
                WHERE TRIM(r.cpf::text) = TRIM(:cpf)
                  AND {filtro_comp_rod}
                  {f_rod}
                ORDER BY lote DESC NULLS LAST
                LIMIT 1
            """)

        rod_res = db.execute(sql_rod, params_try)
        rod_row = rod_res.first()
        rod_tmp = dict(zip(rod_res.keys(), rod_row)) if rod_row else None

        if cab_tmp and rod_tmp:
            cabecalho = cab_tmp
            rodape = rod_tmp
            lote_escolhido = lote
            break

    if not cabecalho and not rodape:
        raise HTTPException(
            status_code=404,
            detail="Cabeçalho e rodapé ausentes para a competência informada (possível divergência de lote/matrícula/empresa)."
        )
    if not cabecalho:
        raise HTTPException(status_code=404, detail="Cabeçalho ausente para a competência/lote/matrícula/empresa.")
    if not rodape:
        raise HTTPException(status_code=404, detail="Rodapé ausente para a competência/lote/matrícula/empresa.")

    if lote_escolhido is not None:
        eventos = [e for e in eventos if e.get("lote") == lote_escolhido]
        if not eventos:
            raise HTTPException(
                status_code=404,
                detail="Eventos não encontrados para o mesmo lote do cabeçalho/rodapé."
            )

    return {
        "tipo": "holerite",
        "competencia_utilizada": competencia,
        "empresa_utilizada": (cabecalho.get("cliente") if cabecalho else None),
        "cliente_nome_utilizado": (cabecalho.get("cliente_nome") if cabecalho else None),
        "matricula_utilizada": params.get("matricula"),
        "cabecalho": cabecalho,
        "eventos": eventos,
        "rodape": rodape
    }
#===========================================================================================================

@router.post("/documents/search")
def buscar_search_documentos(payload: SearchDocumentosRequest):
    try:
        auth_key = login(
            conta=settings.GED_CONTA, usuario=settings.GED_USUARIO, senha=settings.GED_SENHA
        )
    except Exception as e:
        raise HTTPException(502, f"Falha na autenticação no GED: {e}")

    headers = _headers(auth_key)

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

    lista_cp = ["" for _ in nomes_campos]
    for item in payload.cp:
        if item.nome not in nomes_campos:
            raise HTTPException(400, f"Campo '{item.nome}' não existe no template")
        lista_cp[nomes_campos.index(item.nome)] = item.valor

    if not payload.anomes and not payload.anomes_in:
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

        except (requests.HTTPError, requests.RequestException, RuntimeError):
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

def pad_left(valor: str, width: int) -> str:
    return str(valor).strip().zfill(width)

def fmt_num(valor: float) -> str:
    s = f"{valor:,.2f}"
    s = s.replace(",", "X").replace(".", ",")
    return s.replace("X", ".")

def truncate(text: str, max_len: int) -> str:
    text = text or ""
    return text if len(text) <= max_len else text[: max_len - 3] + "..."

def gerar_recibo(cabecalho: dict, eventos: list[dict], rodape: dict, page_number: int = 1) -> bytes:
    
    cabecalho["matricula"] = pad_left(cabecalho["matricula"], 6)
    cabecalho["cliente"]   = pad_left(cabecalho["cliente"],   5)
    cabecalho["empresa"]   = pad_left(cabecalho["empresa"],   3)
    cabecalho["filial"]    = pad_left(cabecalho["filial"],    3)

    adm = datetime.fromisoformat(cabecalho["admissao"])
    cabecalho["admissao"]   = format_date(adm, "dd/MM/yyyy", locale="pt_BR")
    comp = datetime.strptime(cabecalho["competencia"], "%Y%m")
    cabecalho["competencia"] = format_date(comp, "LLLL/yyyy", locale="pt_BR").capitalize()

    empresa_nome = truncate(cabecalho.get("empresa_nome", ""), 50)
    cliente_nome = truncate(cabecalho.get("cliente_nome", ""), 50)
    funcionario  = truncate(cabecalho.get("nome", ""), 30)
    funcao       = truncate(cabecalho.get("funcao_nome", ""), 16)

    pdf = FPDF(format='A4', unit='mm')
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 6, "Recibo de Pagamento de Salário", ln=0)
    pdf.ln(6)

    pdf.set_font("Arial", '', 9)
    pdf.cell(120, 5, f"Empresa: {cabecalho['empresa']} - {cabecalho['filial']} {empresa_nome}", ln=0)
    pdf.cell(0,   5, f"Nº Inscrição: {cabecalho['empresa_cnpj']}", ln=1, align='R')
    pdf.cell(120, 5, f"Cliente: {cabecalho['cliente']} {cliente_nome}",       ln=0)
    pdf.cell(0,   5, f"Nº Inscrição: {cabecalho['cliente_cnpj']}", ln=1, align='R')
    pdf.ln(3)

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

    y_sep = pdf.get_y()
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, y_sep, pdf.w - pdf.r_margin, y_sep)
    pdf.ln(3)

    evt_headers = ["Cód.", "Descrição", "Referência", "Vencimentos", "Descontos"]
    pdf.set_font("Arial", 'B', 9)
    for i, (w, h) in enumerate(zip(col_widths, evt_headers)):
        align = 'C' if i >= 2 else ''
        pdf.cell(w, 6, h, align=align)
    pdf.ln(6)

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

    x0 = pdf.l_margin + col_widths[0] + col_widths[1]
    x1 = x0 + col_widths[2]
    x2 = x1 + col_widths[3]
    pdf.set_line_width(0.2)
    for x in (x0, x1, x2):
        pdf.line(x, y_start, x, y_end)
    pdf.ln(2)

    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)

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

    pdf.set_font("Arial", 'B', 9)
    pdf.cell(0, 6, f"Valor Líquido »» {fmt_num(rodape['valor_liquido'])}", ln=1, align='R')
    pdf.ln(4)

    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)

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
        return response.json()
    except ValueError:
        return {
            "erro": False,
            "base64_raw": response.text
        }