import argparse
import json
import os
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import requests
from requests import Response

AUTHORIZE_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
TOKEN_FILE_PATH = Path("token.json")
REQUEST_TIMEOUT_SECONDS = 30

EXIT_CODE_OK = 0
EXIT_CODE_APP_ERROR = 1
EXIT_CODE_MENU_ERROR = 2
EXIT_CODE_CANCELLED = 130

MENU_ACTION_PRINT_ACCESS_TOKEN = "print_access_token"
POST_TOKEN_MENU_ITEMS = (
    ("あ、いや、アクセストークン取得までいけるか見たかっただけ", MENU_ACTION_PRINT_ACCESS_TOKEN),
)


class AppError(Exception):
    """Base exception for application level errors."""


class ConfigError(AppError):
    """Raised when required configuration is missing or invalid."""


class TokenStoreError(AppError):
    """Raised when token.json cannot be read or written safely."""


class OAuthTokenError(AppError):
    """Raised when token endpoint communication fails."""


class MenuError(AppError):
    """Base exception for interactive menu errors."""


class MenuEnvironmentError(MenuError):
    """Raised when interactive menu cannot be shown in current terminal."""


class MenuInputError(MenuError):
    """Raised when menu input stream is invalid or interrupted unexpectedly."""


class MenuCancelled(MenuError):
    """Raised when user cancels menu explicitly."""


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class MenuItem:
    label: str
    action: str


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析します。"""

    parser = argparse.ArgumentParser(description="freee OAuth token bootstrap utility")
    parser.add_argument(
        "--auth-code",
        default=None,
        help="Authorization code obtained from the browser flow",
    )
    return parser.parse_args()


def require_env(name: str) -> str:
    """環境変数から値を取得し、存在しない場合や空の場合は例外を投げます。"""

    value = os.getenv(name)
    if value is None:
        raise ConfigError(f"Missing required environment variable: {name}")
    stripped = value.strip()
    if not stripped:
        raise ConfigError(f"Environment variable is empty: {name}")
    return stripped


def load_config() -> AppConfig:
    """環境変数からアプリケーション設定を読み込みます。"""

    return AppConfig(
        client_id=require_env("FREEE_CLIENT_ID"),
        client_secret=require_env("FREEE_CLIENT_SECRET"),
        redirect_uri=require_env("FREEE_REDIRECT_URI"),
    )


def build_authorize_url(config: AppConfig) -> tuple[str, str]:
    """認可 URL を構築し、state を生成して返します。"""

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
    """トークンエンドポイントのレスポンスを解析します。"""
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
    """トークンエンドポイントにリクエストを送信し、レスポンスを解析します。"""

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
    """認可コードを使用してアクセストークンを取得します。"""

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
    """リフレッシュトークンを使用してアクセストークンを更新します。"""

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
    """トークン情報を token.json に保存します。"""

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
    """token.json からリフレッシュトークンを読み込みます。"""

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
    """認可コードを再取得するための指示を表示します。"""

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


def require_access_token(token_payload: dict[str, Any]) -> str:
    """トークンレスポンスから access_token を取り出します。"""

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthTokenError("Token endpoint response missing access_token")
    return access_token


def build_post_token_menu_items() -> list[MenuItem]:
    """アクセストークン取得直後のメニュー項目を返します。"""

    return [MenuItem(label=label, action=action) for label, action in POST_TOKEN_MENU_ITEMS]


def ensure_menu_terminal() -> None:
    """メニュー描画に必要な端末条件をチェックします。"""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise MenuEnvironmentError(
            "Interactive menu requires TTY stdin/stdout. Please run in a terminal."
        )


@contextmanager
def raw_stdin_mode() -> Iterator[None]:
    """stdin を一時的に raw モードに切り替えます。"""

    try:
        import termios
        import tty
    except ImportError as exc:
        raise MenuEnvironmentError("Raw terminal input is not supported on this platform.") from exc

    try:
        stdin_fd = sys.stdin.fileno()
    except OSError as exc:
        raise MenuEnvironmentError("stdin file descriptor is not available.") from exc

    try:
        original_mode = termios.tcgetattr(stdin_fd)
    except termios.error as exc:
        raise MenuEnvironmentError("Failed to read terminal mode.") from exc

    try:
        tty.setraw(stdin_fd)
        yield
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, original_mode)


def render_menu(items: list[MenuItem], selected_index: int, *, initial: bool) -> None:
    """メニューを描画します。"""

    if initial:
        print("今回は何をしたい? (↑↓で選択 / Enterで決定 / Ctrl+Cで中断)")
    else:
        sys.stdout.write(f"\x1b[{len(items)}F")

    for index, item in enumerate(items):
        prefix = ">" if index == selected_index else " "
        sys.stdout.write(f"{prefix} {item.label}\x1b[K\n")
    sys.stdout.flush()


def read_menu_key() -> Literal["up", "down", "enter", "ignore"]:
    """メニュー操作用のキー入力を 1 件読み取ります。"""

    first = sys.stdin.buffer.read(1)
    if first == b"":
        raise MenuInputError("Reached EOF while waiting for menu input.")
    if first in (b"\r", b"\n"):
        return "enter"
    if first == b"\x03":
        raise MenuCancelled("Menu cancelled by user.")
    if first == b"\x04":
        raise MenuInputError("Received EOF (Ctrl+D) while waiting for menu input.")
    if first != b"\x1b":
        return "ignore"

    second = sys.stdin.buffer.read(1)
    if second == b"":
        raise MenuInputError("Incomplete escape sequence: missing second byte.")
    if second != b"[":
        return "ignore"

    third = sys.stdin.buffer.read(1)
    if third == b"":
        raise MenuInputError("Incomplete escape sequence: missing third byte.")
    if third == b"A":
        return "up"
    if third == b"B":
        return "down"
    return "ignore"


def select_menu_action(items: list[MenuItem]) -> MenuItem:
    """上下カーソル + Enter でメニュー項目を選択します。"""

    if not items:
        raise MenuInputError("No menu items are available.")

    ensure_menu_terminal()
    selected_index = 0

    with raw_stdin_mode():
        render_menu(items, selected_index, initial=True)
        while True:
            key = read_menu_key()
            if key == "enter":
                return items[selected_index]
            if key == "up":
                next_index = max(0, selected_index - 1)
                if next_index != selected_index:
                    selected_index = next_index
                    render_menu(items, selected_index, initial=False)
                continue
            if key == "down":
                next_index = min(len(items) - 1, selected_index + 1)
                if next_index != selected_index:
                    selected_index = next_index
                    render_menu(items, selected_index, initial=False)


def execute_menu_action(action: str, access_token: str) -> int:
    """選択されたメニューアクションを実行します。"""

    if action == MENU_ACTION_PRINT_ACCESS_TOKEN:
        print(f"access_token: {access_token}")
        return EXIT_CODE_OK

    raise MenuInputError(f"Unknown menu action: {action}")


def run_post_token_menu(access_token: str) -> int:
    """アクセストークン取得直後のメニューを実行します。"""

    selected_item = select_menu_action(build_post_token_menu_items())
    return execute_menu_action(selected_item.action, access_token)


def run_post_token_menu_with_error_mapping(access_token: str) -> int:
    """メニュー例外を終了コードへ変換します。"""

    try:
        return run_post_token_menu(access_token)
    except MenuCancelled as exc:
        print(f"[MENU CANCELLED] {exc}", file=sys.stderr)
        return EXIT_CODE_CANCELLED
    except (MenuEnvironmentError, MenuInputError) as exc:
        print(f"[MENU ERROR] {exc}", file=sys.stderr)
        return EXIT_CODE_MENU_ERROR


def main() -> int:
    """メインの処理を実行します。"""

    args = parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        return EXIT_CODE_APP_ERROR

    auth_code = args.auth_code
    if auth_code:
        try:
            token_payload = exchange_auth_code(config, auth_code)
            save_tokens(token_payload)
            access_token = require_access_token(token_payload)
        except (OAuthTokenError, TokenStoreError) as exc:
            print(f"[AUTH CODE FLOW ERROR] {exc}", file=sys.stderr)
            print_authorize_instructions(config)
            return EXIT_CODE_APP_ERROR

        print("認可コードでトークンを取得し、token.json を更新しました。")
        return run_post_token_menu_with_error_mapping(access_token)

    try:
        refresh_token = load_refresh_token()
    except TokenStoreError as exc:
        print(f"[TOKEN FILE ERROR] {exc}", file=sys.stderr)
        print_authorize_instructions(config)
        return EXIT_CODE_APP_ERROR

    try:
        token_payload = refresh_access_token(config, refresh_token)
        save_tokens(token_payload)
        access_token = require_access_token(token_payload)
    except (OAuthTokenError, TokenStoreError) as exc:
        print(f"[REFRESH FLOW ERROR] {exc}", file=sys.stderr)
        print_authorize_instructions(config)
        return EXIT_CODE_APP_ERROR

    print("リフレッシュトークンでアクセストークンを更新し、token.json を更新しました。")
    return run_post_token_menu_with_error_mapping(access_token)


if __name__ == "__main__":
    raise SystemExit(main())
