"""Application bootstrap and main flow orchestration."""

import sys

from app.actions.registry import execute, to_menu_items
from app.auth.oauth_service import (
    build_authorize_url,
    exchange_auth_code,
    refresh_access_token,
    require_access_token,
)
from app.auth.token_store import load_refresh_token, save_tokens
from app.clients.freee_api_client import FreeeApiClient
from app.config import load_config
from app.context import AppContext
from app.errors import (
    ActionError,
    ApiClientError,
    ConfigError,
    MenuCancelled,
    MenuEnvironmentError,
    MenuInputError,
    OAuthTokenError,
    TokenStoreError,
    UnknownActionError,
)
from app.exit_codes import (
    EXIT_CODE_APP_ERROR,
    EXIT_CODE_CANCELLED,
    EXIT_CODE_MENU_ERROR,
)
from app.menu.controller import select_menu_action


def run(*, auth_code: "str | None") -> int:
    """Run the application and return a process exit code."""

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}", file=sys.stderr)
        return EXIT_CODE_APP_ERROR

    if auth_code:
        return _run_auth_code_flow(config=config, auth_code=auth_code)
    return _run_refresh_flow(config=config)


def _run_auth_code_flow(*, config, auth_code: str) -> int:
    try:
        token_payload = exchange_auth_code(config, auth_code)
        save_tokens(token_payload)
        access_token = require_access_token(token_payload)
    except (OAuthTokenError, TokenStoreError) as exc:
        print(f"[AUTH CODE FLOW ERROR] {exc}", file=sys.stderr)
        print_authorize_instructions(config)
        return EXIT_CODE_APP_ERROR

    print("認可コードでトークンを取得し、token.json を更新しました。")
    return _run_post_token_menu(config=config, access_token=access_token)


def _run_refresh_flow(*, config) -> int:
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
    return _run_post_token_menu(config=config, access_token=access_token)


def _run_post_token_menu(*, config, access_token: str) -> int:
    try:
        context = AppContext(
            config=config,
            access_token=access_token,
            api_client=FreeeApiClient(access_token),
            debug_mode=True,
        )
        items = to_menu_items(debug_mode=context.debug_mode)
        selected_item = select_menu_action(items)
        return execute(selected_item.action_id, context)
    except MenuCancelled as exc:
        print(f"[MENU CANCELLED] {exc}", file=sys.stderr)
        return EXIT_CODE_CANCELLED
    except (MenuEnvironmentError, MenuInputError) as exc:
        print(f"[MENU ERROR] {exc}", file=sys.stderr)
        return EXIT_CODE_MENU_ERROR
    except (UnknownActionError, ActionError, ApiClientError) as exc:
        print(f"[ACTION ERROR] {exc}", file=sys.stderr)
        return EXIT_CODE_APP_ERROR


def print_authorize_instructions(config) -> None:
    """Print instructions to obtain a fresh authorization code."""

    authorize_url, state = build_authorize_url(config)
    print(
        "\n認可コードを再取得してください。以下の URL をブラウザで開いてください:",
        file=sys.stderr,
    )
    print(authorize_url, file=sys.stderr)
    print(f"state: {state}", file=sys.stderr)
    print("\n取得した認可コードで次を実行:", file=sys.stderr)
    print("python main.py --auth-code <認可コード>", file=sys.stderr)
