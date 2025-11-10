from typing import List, Optional
from pydantic import BaseModel, Field


class ChannelOut(BaseModel):
    id: int
    name: str
    channel_type: Optional[str] = None
    public: Optional[str] = None


class MessageOut(BaseModel):
    id: int
    date: Optional[str] = None
    author_id: Optional[List] = None  # [id, "Name"]
    body: Optional[str] = None
    message_type: Optional[str] = None
    model: Optional[str] = None
    res_id: Optional[int] = None


class MessageDetailOut(MessageOut):
    """Mantém os mesmos campos; reservado para evoluções futuras."""
    pass


class SendMessageIn(BaseModel):
    channel_id: int = Field(..., gt=0)
    body: str = Field(..., min_length=1)


class CreateTicketIn(BaseModel):
    channel_id: int
    title: str
    description: str


class CreateTicketOut(BaseModel):
    ticket_id: int
