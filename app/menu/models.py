"""Menu view models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    """A selectable menu item."""

    label: str
    action_id: str
    description: "str | None" = None
    enabled: bool = True
