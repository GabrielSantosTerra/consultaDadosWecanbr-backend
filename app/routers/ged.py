from urllib import response
from fastapi import APIRouter, HTTPException, Form, Depends
from typing import Any
import requests
from pydantic import BaseModel
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

class UltimosDocumentosRequest(BaseModel):
    id_template: int
    cp: List[CampoValor]  # incluirá matrícula como no modelo atual
    campo_anomes: str

class BuscarHolerite(BaseModel):
    matricula: str
    competencia: str

class MontarHolerite(BaseModel):
    matricula: str
    competencia: str
    lote: str

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

    # ✅ Calcular últimos 6 meses
    base = datetime.today().replace(day=1)
    ultimos_6_anomes = [(base - relativedelta(months=i)).strftime("%Y-%m") for i in range(6)]

    # ✅ Filtrar documentos com anomes dentro dos últimos 6 meses
    documentos_filtrados = [
        d for d in documentos_total
        if payload.campo_anomes in d and d[payload.campo_anomes] in ultimos_6_anomes
    ]

    # Ordenar por anomes decrescente
    documentos_filtrados.sort(key=lambda d: d[payload.campo_anomes], reverse=True)

    return JSONResponse(content={
        "documentos": documentos_filtrados,
        "total_encontrado": len(documentos_filtrados)
    })








# ********************************************
@router.post("/documents/holerite/buscar")
def montar_holerite(
    payload: BuscarHolerite,
    db: Session = Depends(get_db),
):
    """
    Busca todos os registros de holerite cuja matrícula e competência
    sejam iguais aos valores passados no payload.
    """

    # ■ Monta e executa o SQL raw
    sql = text("""
        SELECT *
        FROM tb_holerite_cabecalhos
        WHERE matricula   = :matricula
          AND competencia = :competencia
    """)
    result = db.execute(
        sql,
        {
            "matricula": payload.matricula,
            "competencia": payload.competencia,
        },
    )
    rows = result.fetchall()

    # ■ Se não encontrou nada, retorna 404
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Nenhum holerite encontrado para matrícula e competência informados"
        )

    # ■ Converte cada linha em dict (coluna→valor)
    columns = result.keys()
    registros = [dict(zip(columns, row)) for row in rows]

    return registros

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
    params = {"matricula": payload.matricula, "competencia": payload.competencia, "lote": payload.lote}

    # Cabeçalho
    sql_cabecalho = text("""
        SELECT empresa, filial, empresa_nome, empresa_cnpj,
               cliente, cliente_nome, cliente_cnpj,
               matricula, nome, funcao_nome, admissao,
               competencia, lote
        FROM tb_holerite_cabecalhos
        WHERE matricula   = :matricula
          AND competencia = :competencia
          AND lote       = :lote
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
        ORDER BY evento
    """)
    evt_res = db.execute(sql_eventos, params)
    eventos = [dict(zip(evt_res.keys(), row)) for row in evt_res.fetchall()]

    if not eventos:
      raise HTTPException(status_code=404, detail="Eventos não encontrados")

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