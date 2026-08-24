from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import Chat as Tgchat
from aiogram.types import Update
from dishka.integrations.aiogram import CONTAINER_NAME
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Chat
from config import Settings

if TYPE_CHECKING:
    from dishka import AsyncContainer


class MainMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        tg_chat: Tgchat | None = data.get("event_chat")
        if tg_chat is None:
            return
        container: AsyncContainer = data[CONTAINER_NAME]
        settings = await container.get(Settings)
        if not settings.service.CHAT_ID or tg_chat.id in settings.service.CHAT_ID:
            session: AsyncSession = await container.get(AsyncSession)
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
