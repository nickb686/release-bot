from enum import StrEnum
from typing import Literal

from aiogram.filters.callback_data import CallbackData


class ReleaseFormat(StrEnum):
    quote = "quote"
    pre = "pre"
    markdown = "markdown"
    html = "html"


class UserSubActionEnum(StrEnum):
    subscribe = "subscribe"
    add_repos = "add_repos"
    unsubscribe = "unsubscribe"


class PageActionEnum(StrEnum):
    next = "next"
    prev = "prev"


class RepoActionEnum(StrEnum):
    pre = "pre"
    delete = "delete"


class ReleaseFormatActionCallback(CallbackData, prefix="rel_fmt"):
    format: Literal["menu", "quote", "pre", "markdown", "html"]


class UserSubActionCallback(CallbackData, prefix="user_sub"):
    action: UserSubActionEnum
    username: str = ""


class PageActionCallback(CallbackData, prefix="page"):
    action: PageActionEnum
    page: int


class RepoActionCallback(CallbackData, prefix="repo"):
    action: RepoActionEnum
    page: int
    repo_id: int
