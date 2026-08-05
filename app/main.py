import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal, engine
from app.database.models import Chat
from app.github_obj import github_obj
from app.routes import router
from app.tasks import clear_db, poll_github, poll_github_user
from app.telegram_bot import router as tg_router
from config import settings

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class MainMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        chat_id: int = data["event_chat"].id
        if not settings.CHAT_ID or (settings.CHAT_ID and chat_id in settings.CHAT_ID):
            async with self.session_factory() as session:
                chat = await session.get(Chat, chat_id)
                if not chat:
                    chat = Chat(
                        id=chat_id,
                    )
                    session.add(chat)
                    await session.commit()
                data["chat"] = chat
                data["session"] = session
                data["chat_id"] = chat_id
                await handler(event, data)
                await session.commit()


class BotRunner:
    def __init__(self, dp: Dispatcher, bot: Bot):
        self.dp, self.bot = dp, bot

    async def start(self): ...
    async def stop(self): ...


class PollingRunner(BotRunner):
    async def start(self):
        self.task = asyncio.create_task(self.dp.start_polling(self.bot))

    async def stop(self):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task


class WebhookRunner(BotRunner):
    async def start(self):
        await self.bot.set_webhook(settings.webhook_url)

    async def stop(self):
        await self.bot.delete_webhook()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    try:
        app.state.github_obj = github_obj
        app.state.engine = engine
        app.state.session_local = SessionLocal

        dp = Dispatcher()
        dp["github_obj"] = github_obj
        dp.include_router(tg_router)
        dp.update.middleware(MainMiddleware(SessionLocal))
        bot = Bot(settings.TELEGRAM_BOT_TOKEN)
        runner = WebhookRunner(dp, bot) if settings.SITE_URL else PollingRunner(dp, bot)
        await runner.start()
        app.state.dp = dp
        app.state.bot = bot
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            poll_github,
            trigger="interval",
            id="poll_github",
            minutes=settings.GITHUB_POLL_INTERVAL,
            replace_existing=True,
            kwargs={"bot": bot},
        )
        scheduler.add_job(
            poll_github_user,
            trigger="cron",
            id="poll_github_user",
            hour="*/8",
            replace_existing=True,
            kwargs={"bot": bot},
        )

        scheduler.add_job(
            clear_db,
            trigger="cron",
            id="clear_db",
            day_of_week="sun",
            hour=0,
            minute=0,
            replace_existing=True,
        )
        scheduler.start()
        app.state.scheduler = scheduler

        yield
    finally:
        await runner.stop()
        await bot.session.close()
        if scheduler.running:
            scheduler.shutdown()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
