import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from typing import override

from aiogram import Bot, Dispatcher, Router
from aiogram.types import BotCommand

from config import Settings

from .routers import service_router, settings_router, subscription_router

router = Router()
router.include_routers(subscription_router, settings_router, service_router)
__all__ = ["router", "set_commands"]


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="list", description="show your subscriptions"),
        BotCommand(command="edit_list", description="show and edit your subscriptions"),
        BotCommand(
            command="prerelease", description="unsubscribe from repo pre-releases"
        ),
        BotCommand(command="delete", description="unsubscribe from repo releases"),
        BotCommand(command="starred", description="subscribe to user's starred repos"),
        BotCommand(command="settings", description="change output format"),
        BotCommand(command="about", description="information about this bot"),
        BotCommand(command="help", description="brief usage info"),
    ]
    await bot.set_my_commands(commands)


class BotRunner(ABC):
    def __init__(self, dp: Dispatcher, bot: Bot, settings: Settings):
        self.dp, self.bot, self.settings = dp, bot, settings

    @abstractmethod
    async def start(self): ...
    @abstractmethod
    async def stop(self): ...


class PollingRunner(BotRunner):
    @override
    async def start(self):
        self.task = asyncio.create_task(self.dp.start_polling(self.bot))

    @override
    async def stop(self):
        await self.dp.stop_polling()
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task


class WebhookRunner(BotRunner):
    @override
    async def start(self):
        await self.bot.set_webhook(
            self.settings.telegram.webhook_url,
            secret_token=self.settings.telegram.WEBHOOK_SECRET,
        )

    @override
    async def stop(self):
        await self.bot.delete_webhook()
