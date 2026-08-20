from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat as Tgchat
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Chat
from config import settings


class MainMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        tg_chat: Tgchat | None = data.get("event_chat")
        if tg_chat is None:
            return
        if not settings.service.CHAT_ID or tg_chat.id in settings.service.CHAT_ID:
            async with self.session_factory() as session:
                chat = await session.get(Chat, tg_chat.id)
                if not chat:
                    chat = Chat(
                        id=tg_chat.id,
                    )
                    session.add(chat)
                    await session.commit()
                data["chat"] = chat
                data["session"] = session
                data["chat_id"] = chat.id
                await handler(event, data)
                await session.commit()
