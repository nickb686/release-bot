from http import HTTPStatus

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app._version import __version__
from app.database import SessionLocal
from app.database.models import Repo
from app.database.models.chat import Chat
from app.database.models.release import Release
from config import settings

router = APIRouter()


@router.get("/")
async def index(request: Request):
    telegram_bot = request.app.state.bot
    bot_me = await telegram_bot.get_me()
    return (
        f'<a href="https://t.me/{bot_me.username}">{bot_me.first_name}</a> - a telegram bot for GitHub releases v{__version__}.'
        "<br><br>"
        'Source code available at <a href="https://github.com/NIckB686/release-bot">NIckB686/release-bot</a>'
    )


@router.get("/stats")
async def stats():
    async with SessionLocal() as session:
        return {
            "users": session.scalar(select(func.count()).select_from(Chat)),
            "repos": session.scalar(select(func.count()).select_from(Repo)),
            "releases": session.scalar(select(func.count()).select_from(Release)),
        }


@router.post("/telegram")
async def telegram(request: Request) -> Response:
    if not settings.SITE_URL:
        return Response(status_code=HTTPStatus.NOT_IMPLEMENTED)
    dp = request.app.state.dp
    update = await request.json()
    await dp.feed_update(update)
    return Response(status_code=HTTPStatus.OK)
