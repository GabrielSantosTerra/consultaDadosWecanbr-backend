# app/routers/odoo_conversation.py
import os
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

# ---------- Schemas ----------
class MessageIn(BaseModel):
    body_html: str = Field(..., min_length=1)
    author: Optional[str] = None
    at: Optional[str] = None  # ISO8601 opcional (apenas informativo)

class RecordConversationIn(BaseModel):
    ticket_id: Optional[int] = None               # se vier, usa o ticket existente
    subject: str = Field(..., min_length=3)       # se não vier ticket_id, cria com este título
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
            team_id=_resolve_team_id(body.team_id),           # <- usa body.team_id ou HELPDESK_TEAM_ID
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
        raise HTTPException(422, "messages vazio.")
    try:
        svc = OdooHelpdeskService()
        for m in body.messages:
            prefix = f"<p><b>{(m.author or 'Visitante').strip()}</b>"
            if m.at:
                prefix += f" <span style='color:#666'>({m.at})</span>"
            prefix += ":</p>"
            svc.message_post(ticket_id, prefix + m.body_html, message_type="comment")
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
            team_id=_resolve_team_id(body.team_id),           # <- usa body.team_id ou HELPDESK_TEAM_ID
            partner_name=body.partner_name,
            partner_email=body.partner_email,
            tags=body.tags or [],
        )
        for m in body.messages:
            prefix = f"<p><b>{(m.author or 'Visitante').strip()}</b>"
            if m.at:
                prefix += f" <span style='color:#666'>({m.at})</span>"
            prefix += ":</p>"
            svc.message_post(ticket_id, prefix + m.body_html, message_type="comment")
        return {"ok": True, "ticket_id": ticket_id}
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))
