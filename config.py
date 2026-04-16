import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    database_url: str
    session_cookie_name: str
    admin_email: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Demand Forecasting System"),
        secret_key=os.getenv("SECRET_KEY", "change-this-in-production"),
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/forecasting.db"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "forecasting_session"),
        admin_email=os.getenv("ADMIN_EMAIL", "").strip().lower(),
    )
