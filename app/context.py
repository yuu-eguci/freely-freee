"""Shared application context objects."""

from dataclasses import dataclass

from app.clients.freee_api_client import FreeeApiClient
from app.config import AppConfig


@dataclass(frozen=True)
class AppContext:
    """Shared dependencies passed to actions."""

    config: AppConfig
    access_token: str
    api_client: FreeeApiClient
    debug_mode: bool = False
