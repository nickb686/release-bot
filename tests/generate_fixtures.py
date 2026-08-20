# python -m tests.generate_fixtures

import urllib
from pathlib import Path

from app.github_obj import github_obj
from app.telegram_bot.format import format_release_message

DATA_DIR = Path(__file__).resolve().parent / "data"
RELEASE_URLS = (
    "https://github.com/AdguardTeam/AdGuardHome/releases/tag/v0.107.71",
    "https://github.com/SiliconLabs/gecko_sdk/releases/tag/v4.4.5",
    "https://github.com/WinMerge/winmerge/releases/tag/v2.16.50",
    "https://github.com/hoarder-app/hoarder/releases/tag/v0.18.0",
    "https://github.com/immich-app/immich/releases/tag/v1.117.0",
    "https://github.com/immich-app/immich/releases/tag/v1.118.0",
    "https://github.com/immich-app/immich/releases/tag/v1.135.2",
    "https://github.com/immich-app/immich/releases/tag/v1.136.0",
    "https://github.com/jeffvli/feishin/releases/tag/v0.22.0",
    "https://github.com/karakeep-app/karakeep/releases/tag/v0.18.0",
    "https://github.com/karakeep-app/karakeep/releases/tag/v0.29.0",
    "https://github.com/linuxserver/docker-jackett/releases/tag/v0.22.772-ls557",
    "https://github.com/linuxserver/docker-mastodon/releases/tag/v4.3.0-ls108",
    "https://github.com/louislam/dockge/releases/tag/1.5.0",
    "https://github.com/miguelgrinberg/Flask-Migrate/releases/tag/v4.1.0",
    "https://github.com/numpy/numpy/releases/tag/v2.3.2",
    "https://github.com/python-telegram-bot/python-telegram-bot/releases/tag/v22.3",
    "https://github.com/JanisV/release-bot/releases/tag/v0.8.2",
    "https://github.com/swingmx/swingmusic/releases/tag/v2.1.0",
    "https://github.com/sqlitebrowser/sqlitebrowser/releases/tag/v3.13.1",
    "https://github.com/urllib3/urllib3/releases/tag/2.5.0",
)


class DummyRepo:
    def __init__(self):
        self.full_name = ""


class DummyRelease:
    def __init__(self, body=""):
        self.tag_name = ""
        self.title = ""
        self.body = body
        self.html_url = ""
        self.prerelease = False
        self.updated = False


if __name__ == "__main__":
    for github_release_url in RELEASE_URLS:
        path_parts = (
            # pyrefly: ignore [implicit-import]
            urllib.parse.urlparse(github_release_url).path.strip("/").split("/")
        )
        if len(path_parts) < 5 or path_parts[2] != "releases" or path_parts[3] != "tag":
            raise RuntimeError("Wrong GitHub release URL")
        case_name = f"{path_parts[1]}_{path_parts[4]}"

        repo = github_obj.get_repo(f"{path_parts[0]}/{path_parts[1]}")
        release = repo.get_release(path_parts[4])

        orig_path = DATA_DIR / f"{case_name}.orig"
        md_path = DATA_DIR / f"{case_name}.md"
        html_path = DATA_DIR / f"{case_name}.html"
        pre_path = DATA_DIR / f"{case_name}.pre"
        quote_path = DATA_DIR / f"{case_name}.quote"

        with orig_path.open("w", encoding="utf-8", newline="") as f:
            f.write(release.body)

        empty_repo = DummyRepo()
        empty_release = DummyRelease(release.body)
        with md_path.open("w", encoding="utf-8", newline="") as f:
            message, parse_mode, entities = format_release_message(
                # pyrefly: ignore [bad-argument-type]
                None,
                empty_repo,
                empty_release,
            )
            f.write(message)
        with html_path.open("w", encoding="utf-8", newline="") as f:
            message, parse_mode, entities = format_release_message(
                # pyrefly: ignore [bad-argument-type]
                "html",
                empty_repo,
                empty_release,
            )
            f.write(message)
        with pre_path.open("w", encoding="utf-8", newline="") as f:
            message, parse_mode, entities = format_release_message(
                # pyrefly: ignore [bad-argument-type]
                "pre",
                empty_repo,
                empty_release,
            )
            f.write(message)
        with quote_path.open("w", encoding="utf-8", newline="") as f:
            message, parse_mode, entities = format_release_message(
                # pyrefly: ignore [bad-argument-type]
                "quote",
                empty_repo,
                empty_release,
            )
            f.write(message)
