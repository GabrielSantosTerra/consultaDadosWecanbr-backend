# app/routes/routes_livechat_widget.py
import os
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.odooLivechat import OdooLivechatService, OdooError

router = APIRouter(prefix="/odoo/livechat", tags=["odoo-livechat"])

class SnippetResp(BaseModel):
    html: str

@router.get("/channels", response_model=List[Dict[str, Any]])
def list_channels():
    try:
        svc = OdooLivechatService()
        return svc.list_channels()
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/widget-snippet", response_model=SnippetResp)
def get_widget_snippet(channel_id: int = Query(..., ge=1)):
    # Gera o mesmo snippet da aba "Widget" (Odoo Live Chat)
    base = os.getenv("ODOO_URL", "").rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="Defina ODOO_URL no ambiente.")
    css = f'<link href="{base}/im_livechat/external_lib.css" rel="stylesheet" />'
    js1 = f'<script type="text/javascript" src="{base}/im_livechat/external_lib.js"></script>'
    loader = f'<script type="text/javascript" src="{base}/im_livechat/loader/{channel_id}"></script>'
    return {"html": "\n".join([css, js1, loader])}

@router.get("/team-channel")
def resolve_team_channel(team_id: int = Query(..., ge=1)):
    try:
        svc = OdooLivechatService()
        team = svc.get_helpdesk_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="Helpdesk team não encontrado")
        channel = svc.find_channel_by_name(team["name"])
        return {"team": team, "channel": channel}
    except OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))
