"""Debug action that prints the current access token."""

from app.context import AppContext
from app.exit_codes import EXIT_CODE_OK


def print_access_token_action(context: AppContext) -> int:
    """Print the access token once for manual verification."""

    print(f"access_token: {context.access_token}")
    return EXIT_CODE_OK
