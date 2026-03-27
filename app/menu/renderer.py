"""Menu rendering helpers."""

import sys

from app.menu.models import MenuItem


def _write_menu_line(*, selected: bool, label: str) -> None:
    """Write one menu line from column 1 and clear the rest of the line."""

    prefix = ">" if selected else " "
    sys.stdout.write(f"\r{prefix} {label}\x1b[K\n")


def render_menu(items: list[MenuItem], selected_index: int, *, initial: bool) -> None:
    """Render the interactive menu to stdout."""

    if initial:
        print("今回は何をしたい? (↑↓で選択 / Enterで決定 / Ctrl+Cで中断)")
    else:
        sys.stdout.write("\r")
        sys.stdout.write(f"\x1b[{len(items)}F")

    for index, item in enumerate(items):
        _write_menu_line(selected=index == selected_index, label=item.label)
    sys.stdout.flush()
