import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.database import SessionLocal, engine
from app.github_obj import github_obj
from app.routes import router
from app.tasks import clear_db, poll_github, poll_github_user
from app.telegram_bot import PollingRunner, WebhookRunner
from app.telegram_bot import router as tg_router
from app.telegram_bot.middlewares.main_middleware import MainMiddleware
from config import settings

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
