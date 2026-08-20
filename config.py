from pathlib import Path

from pydantic import BaseModel, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

basedir = Path(__file__).resolve().parent


class TelegramBot(BaseModel):
    TOKEN: str
    SITE_URL: str | None = None
    WEBHOOK_SECRET: str | None = None

    @computed_field
    @property
    def webhook_url(self) -> str:
        if self.SITE_URL is None:
            raise ValueError("SITE_URL is not configured")

        return f"{self.SITE_URL}/telegram"


class Database(BaseModel):
    URI: str = Field(
        default=f"sqlite+aiosqlite:///{basedir}/data/db.sqlite",
    )
    ECHO: bool = False


class Service(BaseModel):
    MAX_REPOS_PER_CHAT: int = 0
    GITHUB_POLL_INTERVAL: int = 60
    GITHUB_TOKEN: str | None = None
    CHAT_ID: list[int] = Field(default_factory=list)

    @field_validator("CHAT_ID", mode="before")
    @classmethod
    def split_chat_ids(cls, value) -> list[int]:
        if isinstance(value, str):
            return [int(x.strip()) for x in value.split(",")]
        return value

    @computed_field
    @property
    def PROCESS_PRE_RELEASES(self) -> bool:
        return bool(self.GITHUB_TOKEN)


class Logging(BaseModel):
    LEVEL: str = "INFO"

    @field_validator("LEVEL", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=[".env.example", ".env"],
        extra="ignore",
    )
    telegram: TelegramBot
    db: Database = Database()
    service: Service = Service()
    logging: Logging = Logging()


settings = Settings()
