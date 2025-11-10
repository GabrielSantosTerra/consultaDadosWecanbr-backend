from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Path
from app.utils.odoo_client import OdooClient
from app.schemas.chat import (
    ChannelOut,
    MessageOut,
    MessageDetailOut,
    SendMessageIn,
    CreateTicketIn,
    CreateTicketOut,
)
from config.settings import settings

router = APIRouter(prefix="/livechat")


@router.get("/channels", response_model=List[ChannelOut])
def list_channels(limit: int = Query(50, ge=1, le=200)):
    try:
        client = OdooClient.from_settings()
        return client.list_channels(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Erro ao listar canais: {e}")


@router.get("/messages", response_model=List[MessageOut])
def get_messages(
    channel_id: int = Query(..., gt=0),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        client = OdooClient.from_settings()
        return client.get_messages_by_channel(channel_id=channel_id, limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Erro ao listar mensagens: {e}")


@router.get("/messages/since", response_model=List[MessageOut])
def get_messages_since(
    channel_id: int = Query(..., gt=0),
    after_id: int = Query(..., gt=0, description="Retorna mensagens com id > after_id"),
    limit: int = Query(100, ge=1, le=500),
):
    """
    Retorna mensagens do canal cujo id seja MAIOR que 'after_id'.
    Útil para 'ver a partir do id retornado no /send'.
    """
    try:
        client = OdooClient.from_settings()
        return client.get_messages_since_id(channel_id=channel_id, after_id=after_id, limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Erro ao listar mensagens posteriores: {e}")


@router.get("/message/{message_id}", response_model=MessageDetailOut)
def get_message_by_id(
    message_id: int = Path(..., gt=0),
):
    try:
        client = OdooClient.from_settings()
        row = client.get_message_by_id(message_id)
        if not row:
            raise HTTPException(404, f"Mensagem {message_id} não encontrada")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro ao buscar mensagem: {e}")


@router.post("/send", response_model=int)
def send_message(payload: SendMessageIn):
    try:
        client = OdooClient.from_settings()
        return client.send_message_to_channel(
            channel_id=payload.channel_id, body=payload.body
        )
    except Exception as e:
        raise HTTPException(500, f"Erro ao enviar mensagem: {e}")


@router.post("/ticket", response_model=CreateTicketOut)
def create_ticket(payload: CreateTicketIn):
    try:
        client = OdooClient.from_settings()
        team_id = getattr(settings, "HELPDESK_TEAM_ID", None)
        ticket_id = client.create_helpdesk_ticket(
            name=payload.title, description=payload.description, team_id=team_id
        )
        return {"ticket_id": ticket_id}
    except Exception as e:
        raise HTTPException(500, f"Erro ao criar ticket: {e}")
