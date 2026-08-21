from http import HTTPStatus

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._version import __version__
from app.database.models import Repo
from app.database.models.chat import Chat
from app.database.models.release import Release
from config import Settings

router = APIRouter(route_class=DishkaRoute)


@router.get("/")
async def index(request: Request):
    telegram_bot = request.app.state.bot
    bot_me = await telegram_bot.get_me()
    return HTMLResponse(
        f'<a href="https://t.me/{bot_me.username}">{bot_me.first_name}</a> - a telegram bot for GitHub releases v{__version__}.'
        "<br><br>"
        'Source code available at <a href="https://github.com/NIckB686/release-bot">NIckB686/release-bot</a>'
    )


@router.get("/stats")
async def stats(session: FromDishka[AsyncSession]):
    return {
        "users": session.scalar(select(func.count()).select_from(Chat)),
        "repos": session.scalar(select(func.count()).select_from(Repo)),
        "releases": session.scalar(select(func.count()).select_from(Release)),
    }


@router.post("/telegram")
async def telegram(request: Request, settings: FromDishka[Settings]) -> Response:
    if not settings.telegram.SITE_URL:
        return Response(status_code=HTTPStatus.NOT_IMPLEMENTED)
    if (
        settings.telegram.WEBHOOK_SECRET
        and request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        != settings.telegram.WEBHOOK_SECRET
    ):
        return Response(status_code=HTTPStatus.FORBIDDEN)
    dp = request.app.state.dp
    update = await request.json()
    await dp.feed_update(update)
    return Response(status_code=HTTPStatus.OK)
