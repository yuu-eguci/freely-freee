"""Base action definitions."""

from collections.abc import Callable
from dataclasses import dataclass

from app.context import AppContext

ActionHandler = Callable[[AppContext], int]


@dataclass(frozen=True)
class ActionDefinition:
    """Definition for a selectable action."""

    action_id: str
    menu_label: str
    handler: ActionHandler
    description: "str | None" = None
    debug_only: bool = False
