from pathlib import Path
from unittest.mock import Mock

import pytest
from aiogram.enums import ParseMode

from app.repo_engine import format_release_message

FORMATTING_PARAMS = {
    "quote": {"format": "quote", "mode": ParseMode.HTML, "ext": "quote"},
    "pre": {"format": "pre", "mode": ParseMode.HTML, "ext": "pre"},
    "html": {"format": "html", "mode": ParseMode.MARKDOWN_V2, "ext": "html"},
    "markdown": {"format": None, "mode": ParseMode.MARKDOWN_V2, "ext": "md"},
}


@pytest.fixture
def empty_repo():
    repo = Mock()
    repo.full_name = ""
    return repo


@pytest.fixture
def empty_release():
    release = Mock()
    release.tag_name = ""
    release.name = ""
    release.body = ""
    release.html_url = ""
    release.prerelease = False
    release.updated = False
    return release


NONE_OR_EMPTY_EXPECTED = {
    "quote": "<b></b>\n <a href=''></a>\n<blockquote></blockquote>",
    "pre": "<b></b>\n <a href=''></a>\n<pre></pre>",
    "html": "****\n\n",
    "markdown": "————————\n",
}


@pytest.mark.parametrize("key", FORMATTING_PARAMS.keys())
@pytest.mark.parametrize("body", [None, ""])
def test_format_none_or_empty_input(empty_repo, empty_release, key, body):
    release_note_format = FORMATTING_PARAMS[key]["format"]
    empty_release.body = body

    message, parse_mode, _entities = format_release_message(
        release_note_format, empty_repo, empty_release
    )
    assert parse_mode == FORMATTING_PARAMS[key]["mode"]
    assert message == NONE_OR_EMPTY_EXPECTED[key]


DATA_DIR = Path(__file__).resolve().parent / "data"


def get_test_cases():
    return [file.stem for file in DATA_DIR.glob("*.orig")]


@pytest.mark.parametrize("case_name", get_test_cases())
@pytest.mark.parametrize("key", FORMATTING_PARAMS.keys())
def test_format_input(empty_repo, empty_release, key, case_name):
    release_note_format = FORMATTING_PARAMS[key]["format"]
    ext = FORMATTING_PARAMS[key]["ext"]
    orig_path = DATA_DIR / f"{case_name}.orig"
    dst_path = DATA_DIR / f"{case_name}.{ext}"
    orig_content = orig_path.read_text()
    dst_content = dst_path.read_text()

    empty_release.body = orig_content

    message, parse_mode, _entities = format_release_message(
        release_note_format, empty_repo, empty_release
    )
    if key == "html":
        assert parse_mode in (
            FORMATTING_PARAMS["html"]["mode"],
            FORMATTING_PARAMS["markdown"]["mode"],
        )
    else:
        assert parse_mode == FORMATTING_PARAMS[key]["mode"]
    assert message == dst_content


if __name__ == "__main__":
    pytest.main([__file__])
