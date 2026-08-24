from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler_dishka import setup_dishka as setup_apscheduler_dishka
from dishka import AsyncContainer, Provider, Scope, provide
from dishka.integrations.aiogram import setup_dishka as setup_aiogram_dishka
from github import Auth, Github
from sqlalchemy import StaticPool, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.tasks import clear_db, poll_github, poll_github_user
from app.telegram_bot import BotRunner, PollingRunner, WebhookRunner, set_commands
from app.telegram_bot import router as tg_router
from app.telegram_bot.middlewares.main_middleware import MainMiddleware
from config import Settings


class AppProvider(Provider):
    @provide(scope=Scope.APP)
    def get_settings(self) -> Settings:
        return Settings()

    @provide(scope=Scope.APP)
    def get_github(self, settings: Settings) -> Github:
        auth = (
            Auth.Token(settings.service.GITHUB_TOKEN)
            if settings.service.GITHUB_TOKEN
            else None
        )
        return Github(auth=auth)

    @provide(scope=Scope.APP)
    async def get_db_engine(
        self, settings: Settings
    ) -> AsyncGenerator[AsyncEngine, None]:
        engine = create_async_engine(
            settings.db.URI, echo=settings.db.ECHO, poolclass=StaticPool
        )

        @event.listens_for(engine.sync_engine, "connect")
        # pyrefly: ignore [implicit-any-parameter]
        def set_sqlite_pragma(dbapi_connection, connection_record):
            # Look at https://kerkour.com/sqlite-for-servers
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA temp_store=memory")
            cursor.close()

        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    async def get_db_session_factory(
        self, engine: AsyncEngine
    ) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        yield factory

    @provide(scope=Scope.REQUEST)
    async def get_db_session(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> AsyncGenerator[AsyncSession, Any]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    @provide(scope=Scope.APP)
    async def get_telegram_bot(self, settings: Settings) -> AsyncGenerator[Bot, None]:
        bot = Bot(settings.telegram.TOKEN)
        await set_commands(bot)
        yield bot
        await bot.session.close()

    @provide(scope=Scope.APP)
    async def get_telegram_dispatcher(
        self, container: AsyncContainer
    ) -> AsyncGenerator[Dispatcher, None]:
        dp = Dispatcher()
        setup_aiogram_dishka(container, dp, auto_inject=True)
        dp.include_router(tg_router)
        dp.update.middleware(MainMiddleware())
        yield dp

    @provide(scope=Scope.APP)
    async def get_telegram_runner(
        self, settings: Settings, bot: Bot, dp: Dispatcher
    ) -> AsyncGenerator[BotRunner, Any]:
        runner: PollingRunner | WebhookRunner = (
            WebhookRunner(dp, bot, settings)
            if settings.telegram.SITE_URL
            else PollingRunner(dp, bot, settings)
        )
        await runner.start()
        yield runner
        await runner.stop()

    @provide(scope=Scope.APP)
    async def init_scheduler(
        self, container: AsyncContainer, settings: Settings
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
        scheduler.start()
        yield scheduler
        if scheduler.running:
            scheduler.shutdown(wait=False)
