import logging
import re
from typing import Literal

from aiogram.enums import ParseMode
from aiogram.types import MessageEntity
from github.GitRelease import GitRelease
from github.Repository import Repository
from sulguk import transform_html
from telegramify_markdown import markdownify

from app.github_emoji import github_emoji_map
from app.github_obj import github_obj

SKIPPED_POSTFIX = "\n-=SKIPPED=-"
MAX_TEXT_LENGTH = 4096
github_extra_html_tags_pattern = re.compile(
    '<p align=".*?".*?>|</p>|<a name=".*?">|<picture>.*?</picture>|'
    "</?h[1-4]>|</?sub>|</?sup>|</?details>|</?summary>|</?dl>|</?dt>|"
    "</?dd>|</?em>|</?small>|<br>|<!--.*?-->|<p/>",
    flags=re.DOTALL,
)
github_img_html_tag_pattern = re.compile('<img .*?src="(.*?)".*?>')
github_b_html_tag_pattern = re.compile("<b>(.*?)</b>", flags=re.DOTALL)
github_i_html_tag_pattern = re.compile("<i>(.*?)</i>", flags=re.DOTALL)
github_code_html_tag_pattern = re.compile("<code>(.*?)</code>", flags=re.DOTALL)
github_a_html_tag_pattern = re.compile('<a href="(.*?)".*?>(.*?)</a>', flags=re.DOTALL)
github_emoji_pattern = re.compile(r":[a-z0-9_-]+:")
logger = logging.getLogger(__name__)


def format_header(release_note_format, github_repo: Repository, release: GitRelease):
    current_tag = release.tag_name
    release_title = (
        ""
        if release.name == current_tag
        or release.name == f"v{current_tag}"
        or f"v{release.name}" == current_tag
        else release.name
    )

    if release_note_format in ("quote", "pre"):
        release_header = (
            f"<b>{github_repo.full_name}</b>\n"
            f"{f'<code>{release_title}</code>' if release_title else ''}"
            f" <a href='{release.html_url}'>{current_tag}</a>"
            f"{' <i>pre-release</i>' if release.prerelease else ''}"
            f"{' <i>updated</i>' if release.updated else ''}\n"  # pyrefly: ignore [missing-attribute]
        )
    elif release_note_format == "html":
        release_header = (
            f"**{github_repo.full_name}**<br>"  # GitHub don't process '\n' instead <br> here
            f"{f'`{release_title}`' if release_title else ''}"
            f" [{current_tag}]({release.html_url})"
            f"{' _pre-release_' if release.prerelease else ''}"
            f"{' _updated_' if release.updated else ''}\n\n"  # pyrefly: ignore [missing-attribute]
        )
    else:
        release_header = (
            f"**{github_repo.full_name}**\n"
            f"{f'`{release_title}`' if release_title else ''}"
            f" [{current_tag}]({release.html_url})"
            f"{' _pre-release_' if release.prerelease else ''}"
            f"{' _updated_' if release.updated else ''}\n\n"  # pyrefly: ignore [missing-attribute]
        )

    return release_header


def htmlify_release_body(
    release_note_format, github_repo: Repository, release: GitRelease
):
    header = format_header(release_note_format, github_repo, release)
    release_body = release.body
    release_body = release_body.replace("\r\n", "\n") if release_body else ""
    release_body = f"{header}{release_body}"

    rendered_release_body = github_obj.render_markdown(release_body)
    try:
        result = transform_html(rendered_release_body)
    except ValueError:
        logger.exception(
            "Exception for %s in htmlify_release_body", github_repo.full_name
        )
        release_note_format = ""
        return (
            markdownify_release_message(release_note_format, github_repo, release),
            ParseMode.MARKDOWN_V2,
            None,
        )

    message_len = len(result.text)
    if message_len > MAX_TEXT_LENGTH:
        message_len = MAX_TEXT_LENGTH - len(SKIPPED_POSTFIX)
        result.text = f"{result.text[:message_len]}{SKIPPED_POSTFIX}"

    entities = []
    for entity in result.entities:
        if entity["offset"] >= message_len:
            continue
        if entity["offset"] + entity["length"] >= message_len:
            entity["length"] = message_len - entity["offset"]
        url = None
        if "url" in entity:
            url = entity["url"]
            if isinstance(url, str) and url.startswith("#"):
                continue
        message_entity = MessageEntity(
            type=entity["type"],
            offset=entity["offset"],
            length=entity["length"],
            url=url,
        )
        entities.append(message_entity)

    return result.text, None, entities


def codeify_release_message(
    release_note_format, github_repo: Repository, release: GitRelease
):
    release_body = release.body
    release_body = release_body.replace("\r\n", "\n") if release_body else ""
    release_body = github_extra_html_tags_pattern.sub(
        "",
        release_body,
    )
    release_body = github_img_html_tag_pattern.sub(
        "🖼️\\1",
        release_body,
    )
    if len(release_body) > MAX_TEXT_LENGTH - 256:
        release_body = f"{release_body[: MAX_TEXT_LENGTH - 256]}{SKIPPED_POSTFIX}"

    header = format_header(release_note_format, github_repo, release)
    if release_note_format == "quote":
        message = f"{header}<blockquote>{release_body}</blockquote>"
    else:  # release_note_format == "pre":
        message = f"{header}<pre>{release_body}</pre>"

    return message


def markdownify_release_message(
    release_note_format,
    github_repo: Repository,
    release: GitRelease,
):
    release_body = release.body
    release_body = release_body.replace("\r\n", "\n") if release_body else ""
    release_body = github_extra_html_tags_pattern.sub(
        "",
        release_body,
    )
    release_body = github_img_html_tag_pattern.sub(
        "🖼️\\1",
        release_body,
    )
    if len(release_body) > MAX_TEXT_LENGTH - 256:
        release_body = f"{release_body[: MAX_TEXT_LENGTH - 256]}{SKIPPED_POSTFIX}"

    release_body = github_b_html_tag_pattern.sub(
        "**\\1**",
        release_body,
    )
    release_body = github_i_html_tag_pattern.sub(
        "_\\1_",
        release_body,
    )
    release_body = github_code_html_tag_pattern.sub(
        "`\\1`",
        release_body,
    )
    release_body = github_a_html_tag_pattern.sub(
        "[\\2](\\1)",
        release_body,
    )
    release_body = release_body.replace("<hr>", "---")
    release_body = release_body.replace("[!NOTE]", "**ⓘ Note**")
    release_body = release_body.replace("[!TIP]", "**💡 Tip**")
    release_body = release_body.replace("[!IMPORTANT]", "**❗ Important**")
    release_body = release_body.replace("[!WARNING]", "**⚠️ Warning**")
    release_body = release_body.replace("[!CAUTION]", "**🛑 Caution**")
    if github_emoji_pattern.search(release_body):
        for key, value in github_emoji_map.items():
            release_body = release_body.replace(f":{key}:", value)

    header = format_header(release_note_format, github_repo, release)
    release_body = f"{header}{release_body}"
    message = markdownify(release_body)
    while len(message) >= MAX_TEXT_LENGTH:
        release_body = f"{release_body[:-100]}{SKIPPED_POSTFIX}"
        message = markdownify(release_body)

    return message


def format_release_message(
    release_note_format,
    github_repo: Repository,
    release: GitRelease,
) -> tuple[
    str,
    Literal[ParseMode.HTML, ParseMode.MARKDOWN_V2] | None,
    list[MessageEntity] | None,
]:
    if release_note_format in ("quote", "pre"):
        message = codeify_release_message(release_note_format, github_repo, release)
        parse_mode = ParseMode.HTML
        entities = None
    elif release_note_format == "html":
        message, parse_mode, entities = htmlify_release_body(
            release_note_format,
            github_repo,
            release,
        )
    else:
        message = markdownify_release_message(release_note_format, github_repo, release)
        parse_mode = ParseMode.MARKDOWN_V2
        entities = None

    return message, parse_mode, entities
