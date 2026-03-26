"""Menu controller that coordinates rendering and input."""

from app.errors import MenuInputError
from app.menu.input_reader import ensure_menu_terminal, raw_stdin_mode, read_menu_key
from app.menu.models import MenuItem
from app.menu.renderer import render_menu


def select_menu_action(items: list[MenuItem]) -> MenuItem:
    """Select a menu item with up/down arrows and Enter."""

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
