from typing import List

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Path,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import Response
import base64

from app.utils.odoo_client import OdooClient
from app.schemas.chat import (
    ChannelOut,
    MessageOut,
    MessageDetailOut,
    SendMessageIn,
    CreateTicketIn,
    CreateTicketOut,
    TicketByChannelOut,
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
    try:
        client = OdooClient.from_settings()
        return client.get_messages_since_id(
            channel_id=channel_id,
            after_id=after_id,
            limit=limit,
        )
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
            channel_id=payload.channel_id,
            body=payload.body,
        )
    except Exception as e:
        raise HTTPException(500, f"Erro ao enviar mensagem: {e}")


@router.post("/send-attachment", response_model=int)
async def send_attachment(
    channel_id: int = Form(...),
    body: str | None = Form(None),
    file: UploadFile = File(...),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Arquivo vazio")

    try:
        data_b64 = base64.b64encode(content).decode("ascii")
    except Exception as e:
        raise HTTPException(400, f"Falha ao codificar arquivo em base64: {e}")

    try:
        client = OdooClient.from_settings()
        msg_id = client.send_message_with_attachment(
            channel_id=channel_id,
            body=body or "",
            filename=file.filename or "arquivo",
            mimetype=file.content_type or "application/octet-stream",
            data_base64=data_b64,
        )
        return msg_id
    except Exception as e:
        raise HTTPException(502, f"Erro ao enviar anexo para o Odoo: {e}")


@router.get("/attachment/{attachment_id}")
def download_attachment(
    attachment_id: int = Path(..., gt=0),
):
    try:
        client = OdooClient.from_settings()
        rows = client.search_read(
            "ir.attachment",
            [["id", "=", attachment_id]],
            fields=["id", "name", "mimetype", "datas"],
            limit=1,
        )
    except Exception as e:
        raise HTTPException(500, f"Erro ao buscar attachment: {e}")

    if not rows:
        raise HTTPException(404, f"Anexo {attachment_id} não encontrado")

    att = rows[0]
    data_b64 = att.get("datas")
    if not data_b64:
        raise HTTPException(404, f"Anexo {attachment_id} sem conteúdo (datas vazio)")

    try:
        raw = base64.b64decode(data_b64)
    except Exception as e:
        raise HTTPException(500, f"Erro ao decodificar conteúdo do anexo: {e}")

    filename = att.get("name") or f"attachment-{attachment_id}"
    mimetype = att.get("mimetype") or "application/octet-stream"

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return Response(content=raw, media_type=mimetype, headers=headers)


@router.get("/ticket/by-channel", response_model=TicketByChannelOut)
def ticket_by_channel(channel_id: int = Query(..., gt=0)):
    try:
        client = OdooClient.from_settings()
        ticket_id = client.find_ticket_id_by_channel(channel_id)
        if ticket_id:
            return {"exists": True, "ticket_id": ticket_id}
        return {"exists": False, "ticket_id": None}
    except Exception as e:
        raise HTTPException(500, f"Erro ao verificar ticket do canal: {e}")


@router.post("/ticket", response_model=CreateTicketOut)
def create_ticket(payload: CreateTicketIn):
    try:
        client = OdooClient.from_settings()
        team_id = getattr(settings, "HELPDESK_TEAM_ID", None)

        existing = client.find_ticket_id_by_channel(payload.channel_id)
        if existing:
            return {"ticket_id": existing}

        ticket_id = client.create_helpdesk_ticket(
            name=payload.title,
            description=payload.description,
            team_id=team_id,
            channel_id=payload.channel_id,
        )

        close_body = (
            "Esta conversa no chat ao vivo foi encerrada. "
            "Seu atendimento continuará pelo chamado criado pelo RH."
        )

        try:
            client.send_message_to_channel(
                channel_id=payload.channel_id,
                body=close_body,
            )
        except Exception as e:
            print(f"[ODOO] Falha ao enviar mensagem de encerramento: {e!r}")

        return {"ticket_id": ticket_id}
    except Exception as e:
        raise HTTPException(500, f"Erro ao criar ticket: {e}")


@router.get("/open-sessions")
def list_open_sessions(
    limit: int = Query(50, ge=1, le=200),
):
    try:
        client = OdooClient.from_settings()
        return client.list_open_sessions(limit=limit)
    except Exception as e:
        raise HTTPException(500, f"Erro ao listar sessões abertas: {e}")


@router.post("/presence/online")
def set_presence_online():
    try:
        client = OdooClient.from_settings()
        ok = client.set_current_user_online()
        if not ok:
            raise RuntimeError("write im_status retornou False")
        return {"ok": True, "status": "online"}
    except Exception as e:
        raise HTTPException(500, f"Erro ao marcar operador online: {e}")


@router.post("/presence/offline")
def set_presence_offline():
    try:
        client = OdooClient.from_settings()
        ok = client.set_current_user_offline()
        if not ok:
            raise RuntimeError("write im_status retornou False")
        return {"ok": True, "status": "offline"}
    except Exception as e:
        raise HTTPException(500, f"Erro ao marcar operador offline: {e}")


@router.post("/close/{channel_id}")
def close_channel(
    channel_id: int = Path(..., gt=0),
):
    try:
        client = OdooClient.from_settings()
        ok = client.close_livechat_channel(channel_id)
        if not ok:
            raise HTTPException(500, "Não foi possível encerrar o chat no Odoo")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro ao encerrar chat: {e}")


@router.post("/close")
def close_livechat_channel(channel_id: int = Query(..., gt=0)):
    try:
        client = OdooClient.from_settings()
        ok = client.close_livechat_channel(channel_id)
        if not ok:
            raise HTTPException(500, "Não foi possível encerrar o canal no Odoo")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro ao encerrar canal: {e}")