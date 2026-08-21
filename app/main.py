import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler_dishka import setup_dishka as setup_apscheduler_dishka
from dishka import AsyncContainer, make_async_container
from dishka.integrations.aiogram import AiogramProvider
from dishka.integrations.aiogram import setup_dishka as setup_aiogram_dishka
from dishka.integrations.fastapi import FastapiProvider
from dishka.integrations.fastapi import setup_dishka as setup_fastapi_dishka
from fastapi import FastAPI

from app.di import AppProvider
from app.routes import router
from app.tasks import clear_db, poll_github, poll_github_user
from app.telegram_bot import BotRunner, PollingRunner, WebhookRunner
from app.telegram_bot import router as tg_router
from app.telegram_bot.middlewares.main_middleware import MainMiddleware
from config import Settings


@asynccontextmanager
async def init_logging(settings: Settings):
    logging.basicConfig(
        level=settings.logging.LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    yield logger


@asynccontextmanager
async def init_dispatcher(
    container: AsyncContainer,
) -> AsyncGenerator[Dispatcher, None]:
    dp = Dispatcher()
    setup_aiogram_dishka(container, dp, auto_inject=True)
    dp.include_router(tg_router)
    dp.update.middleware(MainMiddleware())
    yield dp


@asynccontextmanager
async def init_runner(
    dp: Dispatcher, bot: Bot, settings: Settings
) -> AsyncGenerator[BotRunner, None]:
    runner = (
        WebhookRunner(dp, bot) if settings.telegram.SITE_URL else PollingRunner(dp, bot)
    )
    try:
        await runner.start()
        yield runner
    finally:
        await runner.stop()


@asynccontextmanager
async def init_scheduler(
    container: AsyncContainer, settings: Settings
) -> AsyncGenerator[AsyncIOScheduler, None]:
    scheduler = AsyncIOScheduler()
    setup_apscheduler_dishka(container, scheduler, auto_inject=True)
    scheduler.add_job(
        poll_github,
        trigger="interval",
        id="poll_github",
        minutes=settings.service.GITHUB_POLL_INTERVAL,
        replace_existing=True,
    )
    scheduler.add_job(
        poll_github_user,
        trigger="cron",
        id="poll_github_user",
        hour="*/8",
        replace_existing=True,
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
    try:
        scheduler.start()
        yield scheduler
    finally:
        if scheduler.running:
            scheduler.shutdown()


@asynccontextmanager
async def create_container() -> AsyncGenerator[AsyncContainer, Any]:
    container = make_async_container(
        AppProvider(),
        AiogramProvider(),
        FastapiProvider(),
    )
    yield container
    await container.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with AsyncExitStack() as stack:
        container = await stack.enter_async_context(create_container())
        settings = await container.get(Settings)
        await stack.enter_async_context(init_logging(settings))
        bot = await container.get(Bot)
        dp = await stack.enter_async_context(init_dispatcher(container))
        await stack.enter_async_context(init_runner(dp, bot, settings))
        scheduler = await stack.enter_async_context(init_scheduler(container, settings))
        app.state.dp, app.state.bot, app.state.scheduler = dp, bot, scheduler
        setup_fastapi_dishka(container, app)
        yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
