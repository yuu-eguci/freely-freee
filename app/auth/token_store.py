"""Persistent token file helpers."""

import json
from pathlib import Path
from typing import Any

from app.errors import TokenStoreError

TOKEN_FILE_PATH = Path("token.json")


def save_tokens(token_payload: dict[str, Any]) -> None:
    """Write access and refresh tokens to token.json."""

    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise TokenStoreError("Cannot save token.json: access_token is missing")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise TokenStoreError("Cannot save token.json: refresh_token is missing")

    content = {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
    try:
        TOKEN_FILE_PATH.write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise TokenStoreError(f"Failed to write {TOKEN_FILE_PATH}: {exc}") from exc


def load_refresh_token() -> str:
    """Read the refresh token from token.json."""

    if not TOKEN_FILE_PATH.exists():
        raise TokenStoreError(f"{TOKEN_FILE_PATH} does not exist")
    if not TOKEN_FILE_PATH.is_file():
        raise TokenStoreError(f"{TOKEN_FILE_PATH} exists but is not a file")

    try:
        raw = TOKEN_FILE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise TokenStoreError(f"Failed to read {TOKEN_FILE_PATH}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TokenStoreError(f"{TOKEN_FILE_PATH} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise TokenStoreError(f"{TOKEN_FILE_PATH} must be a JSON object")

    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise TokenStoreError(f"{TOKEN_FILE_PATH} is missing refresh_token")
    return refresh_token.strip()
