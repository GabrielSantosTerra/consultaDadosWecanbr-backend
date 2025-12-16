from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator


class ChannelOut(BaseModel):
    id: int
    name: str
    channel_type: Optional[str] = None
    public: Optional[str] = None


class AttachmentOut(BaseModel):
    id: int
    name: str
    mimetype: Optional[str] = None
    url: str


class MessageOut(BaseModel):
    id: int
    date: Optional[str] = None
    author_id: Optional[List[Union[int, str]]] = None
    body: Optional[str] = None
    message_type: Optional[str] = None
    model: Optional[str] = None
    res_id: Optional[int] = None
    attachments: List[AttachmentOut] = Field(default_factory=list)

    @field_validator("author_id", mode="before")
    @classmethod
    def normalize_author_id(cls, v):
        if v is False:
            return None
        return v


class MessageDetailOut(MessageOut):
    pass


class LivechatSessionOut(BaseModel):
    session_id: int
    channel_id: int
    visitor_name: Optional[str] = None
    state: Optional[str] = None


class SendMessageIn(BaseModel):
    channel_id: int = Field(..., gt=0)
    body: str = Field(..., min_length=1)


class CreateTicketIn(BaseModel):
    channel_id: int
    title: str
    description: str


class CreateTicketOut(BaseModel):
    ticket_id: int


class TicketByChannelOut(BaseModel):
    exists: bool
    ticket_id: Optional[int] = None