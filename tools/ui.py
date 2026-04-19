"""Shared interactive UI helpers for the master CLI."""

import questionary
from rich.console import Console

from .db.crud import list_projects

console = Console()


def pick_project() -> tuple[str, object] | tuple[None, None]:
    """Interactively select a project.

    Displays existing projects as an arrow-key / j-k navigable list.
    Falls back to manual text entry if no projects exist.

    Returns:
        (project_id, project) if selected, (None, None) if cancelled.
    """
    projects = list_projects()

    if not projects:
        console.print("[red]尚無任何專案，請先至專案管理新增。[/red]")
        return None, None

    choices = [
        questionary.Choice(
            title=f"{p.id}  [{p.env_prefix}]  {p.display_name}",
            value=p,
        )
        for p in projects
    ]
    choices.append(questionary.Choice(title="← 取消", value=None))

    project = questionary.select(
        "選擇專案（↑↓ 或 j/k 移動，Enter 確認）：",
        choices=choices,
        use_shortcuts=False,
        style=questionary.Style([
            ("highlighted", "bold cyan"),
            ("selected",    "bold green"),
        ]),
    ).ask()

    if project is None:
        return None, None

    return project.id, project
