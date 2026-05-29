"""Configuration loading helpers."""

import os
from dataclasses import dataclass

from app.errors import ConfigError


@dataclass(frozen=True)
class AppConfig:
    """Configuration derived from environment variables."""

    client_id: str
    client_secret: str
    redirect_uri: str
    target_company_id: int


def require_env(name: str) -> str:
    """Read a required environment variable."""

    value = os.getenv(name)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    stripped = value.strip()
    if not stripped:
        raise ConfigError(f"Environment variable is empty: {name}")
    return stripped


def require_int_env(name: str) -> int:
    """Read a required integer environment variable."""

    raw_value = require_env(name)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} is not a valid integer: {raw_value!r}") from exc


def load_config() -> AppConfig:
    """Load application configuration from the environment."""

    return AppConfig(
        client_id=require_env("FREEE_CLIENT_ID"),
        client_secret=require_env("FREEE_CLIENT_SECRET"),
        redirect_uri=require_env("FREEE_REDIRECT_URI"),
        target_company_id=require_int_env("TARGET_COMPANY_ID"),
    )
