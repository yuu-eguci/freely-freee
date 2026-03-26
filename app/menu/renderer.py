"""Menu rendering helpers."""

import sys

from app.menu.models import MenuItem


def render_menu(items: list[MenuItem], selected_index: int, *, initial: bool) -> None:
    """Render the interactive menu to stdout."""

    if initial:
        print("今回は何をしたい? (↑↓で選択 / Enterで決定 / Ctrl+Cで中断)")
    else:
        sys.stdout.write(f"\x1b[{len(items)}F")

    for index, item in enumerate(items):
        prefix = ">" if index == selected_index else " "
        sys.stdout.write(f"{prefix} {item.label}\x1b[K\n")
    sys.stdout.flush()
