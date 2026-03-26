import argparse
import json
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from requests import Response

AUTHORIZE_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
TOKEN_FILE_PATH = Path("token.json")
REQUEST_TIMEOUT_SECONDS = 30


class AppError(Exception):
    """Base exception for application level errors."""


class ConfigError(AppError):
    """Raised when required configuration is missing or invalid."""


class TokenStoreError(AppError):
    """Raised when token.json cannot be read or written safely."""


class OAuthTokenError(AppError):
    """Raised when token endpoint communication fails."""


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="freee OAuth token bootstrap utility")
    parser.add_argument(
        "--auth-code",
        default=None,
        help="Authorization code obtained from the browser flow",
    )
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    stripped = value.strip()
    if not stripped:
        raise ConfigError(f"Environment variable is empty: {name}")
    return stripped


def load_config() -> AppConfig:
    return AppConfig(
        client_id=require_env("FREEE_CLIENT_ID"),
        client_secret=require_env("FREEE_CLIENT_SECRET"),
        redirect_uri=require_env("FREEE_REDIRECT_URI"),
    )


def build_authorize_url(config: AppConfig) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "state": state,
            "prompt": "select_company",
        }
    )
    return f"{AUTHORIZE_URL}?{params}", state


def parse_token_response(response: Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthTokenError(
            f"Token endpoint returned non-JSON response (status={response.status_code})"
        ) from exc

    if response.status_code >= 400:
        error = payload.get("error")
        description = payload.get("error_description")
        message = payload.get("message")
        details = [part for part in [error, description, message] if isinstance(part, str) and part]
        detail_text = ", ".join(details) if details else "No detailed error message"
        raise OAuthTokenError(
            f"Token endpoint error (status={response.status_code}): {detail_text}"
        )

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthTokenError("Token endpoint response missing access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise OAuthTokenError("Token endpoint response missing refresh_token")

    return payload


def post_token(payload: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(
            TOKEN_URL,
            data=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise OAuthTokenError("Token endpoint request timed out") from exc
    except requests.ConnectionError as exc:
        raise OAuthTokenError("Could not connect to token endpoint") from exc
    except requests.RequestException as exc:
        raise OAuthTokenError(f"Token endpoint request failed: {exc}") from exc

    return parse_token_response(response)


def exchange_auth_code(config: AppConfig, auth_code: str) -> dict[str, Any]:
    if not auth_code.strip():
        raise OAuthTokenError("Received an empty authorization code")
    return post_token(
        {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": auth_code.strip(),
            "redirect_uri": config.redirect_uri,
        }
    )


def refresh_access_token(config: AppConfig, refresh_token: str) -> dict[str, Any]:
    if not refresh_token.strip():
        raise OAuthTokenError("Refresh token is empty")
    return post_token(
        {
            "grant_type": "refresh_token",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": refresh_token.strip(),
        }
    )


def save_tokens(token_payload: dict[str, Any]) -> None:
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


def print_authorize_instructions(config: AppConfig) -> None:
    authorize_url, state = build_authorize_url(config)
    print(
        "\n認可コードを再取得してください。以下の URL をブラウザで開いてください:",
        file=sys.stderr,
    )
    print(authorize_url, file=sys.stderr)
    print(f"state: {state}", file=sys.stderr)
    print(
        "\n取得した認可コードで次を実行:",
        file=sys.stderr,
    )
    print("python main.py --auth-code <認可コード>", file=sys.stderr)


def main() -> int:
    # とりあえずコマンドライン引数を取得します。
    args = parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        return 1

    # AUTH_CODE ある -> それ使ってアクセス/リフレッシュトークンを取得 -> token.json に保存。
    # ない -> もう token.json があるやろ、っていう気持ちで実行されたと思われる -> 続行。
    auth_code = args.auth_code
    if auth_code:
        try:
            token_payload = exchange_auth_code(config, auth_code)
            save_tokens(token_payload)
        except (OAuthTokenError, TokenStoreError) as exc:
            print(f"[AUTH CODE FLOW ERROR] {exc}", file=sys.stderr)
            print_authorize_instructions(config)
            return 1

        print("認可コードでトークンを取得し、token.json を更新しました。")
        return 0

    # いや token.json ねーじゃねーかｗ -> 終了。
    try:
        refresh_token = load_refresh_token()
    except TokenStoreError as exc:
        print(f"[TOKEN FILE ERROR] {exc}", file=sys.stderr)
        print_authorize_instructions(config)
        return 1

    # リフレッシュトークンからアクセストークンを取得します。
    try:
        token_payload = refresh_access_token(config, refresh_token)
        save_tokens(token_payload)
    except (OAuthTokenError, TokenStoreError) as exc:
        print(f"[REFRESH FLOW ERROR] {exc}", file=sys.stderr)
        print_authorize_instructions(config)
        return 1

    print("リフレッシュトークンでアクセストークンを更新し、token.json を更新しました。")
    return 0


if __name__ == "__main__":
    # 0 とか 1 の返り値を sys.exit() に渡すやつです。
    # NOTE: へー、こんなのあったんだ。
    raise SystemExit(main())
