from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    BOT_TOKEN: str
    ADMIN_IDS: list[int] = []
    SUPPORT_USERNAME: str = "support"  # ник поддержки без @, задаётся в .env

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/replly.db"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Resend (outreach)
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "Replly <team@example.com>"

    # Сайт продукта для ссылок в сообщениях владельцу
    SITE_URL: str = "https://example.com"

    # Follow-ups
    FOLLOWUP_1_DAYS: int = 2
    FOLLOWUP_2_DAYS: int = 5

    # Limits
    MAX_KNOWLEDGE_BASE_SIZE: int = 10000
    MAX_FREE_DIALOGUES: int = 0  # no free tier, payment required
    FREE_TRIAL_DAYS: int = 1  # 24 часа

    # Stars pricing (Telegram Stars)
    STARS_PRICE_START: int = 500     # ~2990 RUB
    STARS_PRICE_BUSINESS: int = 850  # ~4990 RUB
    STARS_PRICE_PRO: int = 2500      # ~14990 RUB

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> list[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []


settings = Settings()  # type: ignore[call-arg]
