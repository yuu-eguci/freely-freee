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


def require_env(name: str) -> str:
    """Read a required environment variable."""

    value = os.getenv(name)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    stripped = value.strip()
    if not stripped:
        raise ConfigError(f"Environment variable is empty: {name}")
    return stripped


def load_config() -> AppConfig:
    """Load application configuration from the environment."""

    return AppConfig(
        client_id=require_env("FREEE_CLIENT_ID"),
        client_secret=require_env("FREEE_CLIENT_SECRET"),
        redirect_uri=require_env("FREEE_REDIRECT_URI"),
    )
