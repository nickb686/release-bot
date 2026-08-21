from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot
from dishka import Provider, Scope, provide
from github import Auth, Github
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.telegram_bot import set_commands
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
    ) -> AsyncGenerator[AsyncEngine, Any]:
        engine = create_async_engine(
            settings.db.URI,
            echo=settings.db.ECHO,
        )

        @event.listens_for(engine.sync_engine, "connect")
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
    def get_db_session_factory(
        self, engine: AsyncEngine
    ) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            engine,
            expire_on_commit=False,
        )

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
    async def get_telegram_bot(self, settings: Settings) -> AsyncGenerator[Bot, Any]:
        bot = Bot(settings.telegram.TOKEN)
        try:
            await set_commands(bot)
            yield bot
        finally:
            await bot.session.close()
