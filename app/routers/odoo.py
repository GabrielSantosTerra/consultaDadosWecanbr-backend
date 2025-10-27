# app/routes/routes_odoo_helpdesk.py
import os
import re
import html
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.services.odooHelpdesk import OdooHelpdeskService, OdooError

router = APIRouter(prefix="/odoo/helpdesk", tags=["odoo-helpdesk"])

# ---------- helpers ----------
def _env_team_id() -> Optional[int]:
    raw = os.getenv("HELPDESK_TEAM_ID")
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None

def _resolve_team_id(body_team: Optional[int]) -> Optional[int]:
    """Se o body não mandar team_id, usa HELPDESK_TEAM_ID do .env (se existir)."""
    return body_team if body_team is not None else _env_team_id()

_TAG_RE = re.compile(r"<[^>]+>")

def _html_to_text(s: str) -> str:
    """
    Remove QUALQUER marcação HTML e faz unescape básico.
    Ex.: '<p>oi<br>tudo</p>' -> 'oi tudo'
    """
    if not s:
        return ""
    txt = _TAG_RE.sub("", s)
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    return html.unescape(txt).strip()

def _safe_plain(s: str) -> str:
    """
    Garante que vamos enviar ao Odoo apenas TEXTO (sem tags).
    """
    return html.escape(s or "", quote=False)

# ---------- Schemas ----------
class MessageIn(BaseModel):
    body: Optional[str] = None              # TEXTO PURO
    body_html: Optional[str] = None         # compat (se front ainda enviar HTML)
    author: Optional[str] = None            # informativo (ignorado na postagem)
    at: Optional[str] = None                # informativo (ignorado na postagem)

class RecordConversationIn(BaseModel):
    ticket_id: Optional[int] = None
    subject: str = Field(..., min_length=3)
    team_id: Optional[int] = None
    partner_name: Optional[str] = None
    partner_email: Optional[str] = None
    tags: Optional[List[str]] = None
    messages: List[MessageIn] = Field(..., min_items=1)

class TicketOut(BaseModel):
    ok: bool
    ticket_id: int

# ---------- Endpoints ----------
@router.get("/teams", response_model=List[dict])
def list_teams():
    try:
        svc = OdooHelpdeskService()
        teams = svc.list_teams()
        return [{"id": t["id"], "name": t["name"]} for t in teams]
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tickets", response_model=TicketOut)
def create_ticket(body: RecordConversationIn):
    try:
        svc = OdooHelpdeskService()
        if body.ticket_id:
            return {"ok": True, "ticket_id": body.ticket_id}
        tid = svc.create_ticket(
            name=body.subject,
            description_html="<p>Ticket criado via API</p>",
            team_id=_resolve_team_id(body.team_id),
            partner_name=body.partner_name,
            partner_email=body.partner_email,
            tags=body.tags or [],
        )
        return {"ok": True, "ticket_id": tid}
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tickets/{ticket_id}/messages", response_model=TicketOut)
def append_messages(ticket_id: int, body: RecordConversationIn):
    if not body.messages:
        raise HTTPException(status_code=422, detail="messages vazio.")
    try:
        svc = OdooHelpdeskService()
        for m in body.messages:
            # 1) prioriza TEXTO
            raw_text = (m.body or "").strip()
            if not raw_text and m.body_html:
                raw_text = _html_to_text(m.body_html)
            if not raw_text:
                continue
            # 2) envia texto escapado (sem tags)
            final_text = _safe_plain(raw_text)
            svc.message_post(ticket_id, final_text, message_type="comment")
        return {"ok": True, "ticket_id": ticket_id}
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/record", response_model=TicketOut)
def record_conversation(body: RecordConversationIn):
    try:
        svc = OdooHelpdeskService()
        ticket_id = body.ticket_id or svc.create_ticket(
            name=body.subject,
            description_html="<p>Transcrição registrada via API</p>",
            team_id=_resolve_team_id(body.team_id),
            partner_name=body.partner_name,
            partner_email=body.partner_email,
            tags=body.tags or [],
        )
        for m in body.messages:
            raw_text = (m.body or "").strip()
            if not raw_text and m.body_html:
                raw_text = _html_to_text(m.body_html)
            if not raw_text:
                continue
            final_text = _safe_plain(raw_text)
            svc.message_post(ticket_id, final_text, message_type="comment")
        return {"ok": True, "ticket_id": ticket_id}
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))
