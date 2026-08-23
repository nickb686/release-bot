import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import make_async_container
from dishka.integrations.aiogram import AiogramProvider
from dishka.integrations.fastapi import FastapiProvider
from dishka.integrations.fastapi import setup_dishka as setup_fastapi_dishka
from fastapi import FastAPI

from app.di import AppProvider
from app.routes import router
from app.telegram_bot import BotRunner
from config import Settings


def init_logging(settings: Settings):
    logging.basicConfig(
        level=settings.logging.LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


logger = logging.getLogger(__name__)

container = make_async_container(AppProvider(), AiogramProvider(), FastapiProvider())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = await container.get(Settings)
    init_logging(settings)
    await container.get(BotRunner)
    await container.get(AsyncIOScheduler)
    try:
        yield
    finally:
        logger.debug("Container is closing...")
        await container.close()
        logger.debug("Container is closed.")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    setup_fastapi_dishka(container, app)
    app.include_router(router)
    return app


app = create_app()
