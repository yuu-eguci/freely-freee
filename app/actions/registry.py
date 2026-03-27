"""Registry for menu actions."""

from app.actions.base import ActionDefinition
from app.actions.bulk_attendance import handler as bulk_attendance_handler
from app.actions.bulk_attendance_reset import handler as bulk_attendance_reset_handler
from app.actions.print_access_token import print_access_token_action
from app.context import AppContext
from app.errors import ActionRegistrationError, UnknownActionError
from app.menu.models import MenuItem

ACTIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        action_id="bulk_attendance",
        menu_label="指定の月に自分の勤怠を詰め込む",
        handler=bulk_attendance_handler,
    ),
    ActionDefinition(
        action_id="bulk_attendance_reset",
        menu_label="指定の月の自分の勤怠をリセットする",
        handler=bulk_attendance_reset_handler,
    ),
    ActionDefinition(
        action_id="print_access_token",
        menu_label="あ、いや、アクセストークン取得までいけるか見たかっただけ",
        handler=print_access_token_action,
        debug_only=True,
    ),
)


def _validate_actions() -> None:
    seen_ids: set[str] = set()
    for action in ACTIONS:
        if not action.action_id:
            raise ActionRegistrationError("action_id must not be empty")
        if not action.menu_label:
            raise ActionRegistrationError(f"menu_label must not be empty: {action.action_id}")
        if not callable(action.handler):
            raise ActionRegistrationError(f"handler must be callable: {action.action_id}")
        if action.action_id in seen_ids:
            raise ActionRegistrationError(f"Duplicate action_id: {action.action_id}")
        seen_ids.add(action.action_id)


def to_menu_items(*, debug_mode: bool) -> list[MenuItem]:
    """Convert action definitions into menu items."""

    _validate_actions()
    items: list[MenuItem] = []
    for action in ACTIONS:
        if action.debug_only and not debug_mode:
            continue
        items.append(
            MenuItem(
                label=action.menu_label,
                action_id=action.action_id,
                description=action.description,
                enabled=True,
            )
        )
    return items


def execute(action_id: str, context: AppContext) -> int:
    """Execute a registered action by id."""

    _validate_actions()
    for action in ACTIONS:
        if action.action_id == action_id:
            return action.handler(context)
    raise UnknownActionError(f"Unknown action_id: {action_id}")
