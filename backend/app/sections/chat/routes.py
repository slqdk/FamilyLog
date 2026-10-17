"""Alf on the front page - /api/chat/... (FamilyLog 0.2.0). Every signed-in
account, family included, has its own conversation; nobody reads another's."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import chat

router = APIRouter()


class SendBody(BaseModel):
    message: str
    lat: float | None = None
    lng: float | None = None


@router.get("/api/chat/state")
def chat_state(request: Request):
    return chat.view(request.state.user["id"])


@router.post("/api/chat/send")
async def chat_send(body: SendBody, request: Request):
    phone = None
    if body.lat is not None and body.lng is not None \
            and -90 <= body.lat <= 90 and -180 <= body.lng <= 180:
        phone = (body.lat, body.lng)
    try:
        return chat.send(request.state.user, body.message, phone)
    except chat.Busy as exc:
        raise HTTPException(409, str(exc))
    except chat.Invalid as exc:
        raise HTTPException(400, str(exc))


@router.post("/api/chat/stop")
async def chat_stop(request: Request):
    return chat.stop(request.state.user["id"])


@router.post("/api/chat/new")
async def chat_new(request: Request):
    chat.new_conversation(request.state.user["id"])
    return chat.view(request.state.user["id"])
