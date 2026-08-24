[![Python 3.12](https://img.shields.io/badge/python-3.12-x.svg)](https://www.python.org/downloads/release/python-312/)
[![GitHub license](https://img.shields.io/github/license/JanisV/release-bot.svg)](https://github.com/JanisV/release-bot/blob/main/LICENSE)
[![Latest build](https://github.com/JanisV/release-bot/actions/workflows/docker.yml/badge.svg)](https://github.com/JanisV/release-bot/pkgs/container/release-bot)

# release-bot

A Telegram bot that monitors GitHub repositories and notifies users about new releases.

release-bot is a modernized fork of JanisV/release-bot.

It preserves the original functionality while replacing the underlying architecture with modern Python libraries, frameworks, and development practices.

![Screenshot](https://github.com/user-attachments/assets/7587a21e-72c3-4462-9b19-d321f85c68dc)

## Alternatives

This bot is inspired by [new(releases)](https://newreleases.io/), [Github releases notify bot](https://github.com/pyatyispyatil/github-releases-notify-bot) and [release-bot](https://github.com/chofnar/release-bot).

Other similar tools:

- [Dockcheck](https://github.com/mag37/dockcheck) - CLI tool to automate docker image updates;
- [Renovate](https://docs.renovatebot.com/) - Automated dependency updates

## Why this fork?

The goal of this fork is not to change the bot's functionality, but to modernize its implementation.

Key architectural changes include:

- Flask → FastAPI
- python-telegram-bot → aiogram
- Flask-SQLAlchemy → SQLAlchemy 2.x
- Flask-Migrate → Alembic
- Flask-APScheduler → APScheduler
- pip → uv
- SQLAlchemy 2.x declarative models
- Modern SQLAlchemy query syntax
- Updated project structure
- Updated dependencies

## Features

- Easy subscription to repo by owner/name, GitHub/PyPI/npm URL or uploading requirements.txt or package.json file
- Auto subscription to starred repos
- Ready for self-hosting, has docker image
- Supports both polling and webhooks
- Works locally without a public IP address or a domain name
- Only a Telegram bot token is required

## Commands

- `/start` - show welcome message
- `/about` - information about this bot
- `/help` - brief usage info
- `/list` - show your subscriptions
- `/editlist` - show and edit your subscriptions
- `/starred username` - subscribe to user's starred repos
- `/starred` - unsubscribe from user's starred repos
- `/settings` - change output format
- `/stats` - basic server statistics
- `/test URL` - show specified release message

## Stack

- Python 3.12
- FastAPI
- aiogram
- PyGithub
- SQLAlchemy 2.x
- Alembic
- APScheduler
- uv
- telegramify_markdown
- sulguk

## Architecture

The application consists of several loosely coupled components:

- `FastAPI` provides the application lifecycle and webhook endpoint.
- `aiogram` handles Telegram updates and command routing.
- `APScheduler` periodically checks GitHub for new releases.
- `SQLAlchemy` manages database access.
- `Alembic` manages schema migrations.

## Running it yourself

### With docker

Using docker compose:

```yaml
services:
  release-bot:
    container_name: release-bot
    build: .
    restart: unless-stopped
    environment:
      - TELEGRAM_BOT_TOKEN=<telegram_token>
      #- GITHUB_TOKEN=<github_token> # optional
      #- SITE_URL=https://<your_domain_name> # optional
    ports:
      - 8000:8000
    volumes:
      - /path/to/data:/app/data
```

or docker run:
`docker build -t release-bot .`
`docker run -p 8000:8000 -e TELEGRAM_BOT_TOKEN="<telegram_token>" -v /path/to/data:/app/data -d --name release-bot .`

### From source

Look at Development section

### Set the necessary env vars

`TELEGRAM_BOT_TOKEN` - get this from [BotFather](https://t.me/botfather). You'll need to create a bot.

`GITHUB_TOKEN` - (optional) GitHub personal access token (classic) or fine-grained personal access token. When not specified working well for about 20 repos. More info at [Rate limits for the REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2022-11-28).

`SITE_URL` - (optional) URL used for listening for incoming requests from the Telegram servers. When not specified uses polling instead webhooks. More info at [Marvin's Marvellous Guide to All Things Webhook](https://core.telegram.org/bots/webhooks).

`CHAT_ID` - (optional) Only messages from the specified chat ID are accepted. Can be a comma separated list. You can get your chat ID with [@getmyid_bot](https://t.me/getmyid_bot). If not specified, all messages are accepted.

`DATABASE_URI` - (optional) When not specified local SQLite uses.

`MAX_REPOS_PER_CHAT` - (optional) Limit number of repos per user. Default 0 - unlimited.

`LOG_LEVEL` - (optional) Default INFO.

`GITHUB_POLL_INTERVAL` - (optional) How often to poll GitHub, minutes. Default 60.

## Development

Setup env vars (you can use .env file instead) and run:

### Running with uv (recommended)

```sh
uv sync
uv run alembic upgrade head
uv run fastapi dev app/main.py --host 0.0.0.0
```

For use webhooks locally, you may want to use [localhost.run](https://localhost.run/).

## Credits

This project is based on the original
[JanisV/release-bot](https://github.com/JanisV/release-bot).

Many thanks to the original author for creating and maintaining the project.
