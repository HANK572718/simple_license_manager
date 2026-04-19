"""Project management commands for the master CLI."""

from datetime import datetime

from rich.console import Console
from rich.prompt import IntPrompt, Prompt
from rich.table import Table

from .db.crud import create_project, get_project, list_projects

console = Console()


def cmd_project_menu() -> None:
    """Display the project sub-menu and dispatch commands."""
    while True:
        console.print("\n[bold cyan]── 專案管理 ──[/bold cyan]")
        console.print("  \\[n] 新增專案")
        console.print("  \\[l] 列出所有專案")
        console.print("  \\[b] 返回主選單")

        choice = Prompt.ask("選擇").strip().lower()

        if choice == "n":
            _create_project()
        elif choice == "l":
            _list_projects()
        elif choice == "b":
            return


def _create_project() -> None:
    """Interactive prompt to create a new project."""
    console.print("\n[bold]新增專案[/bold]")
    project_id = Prompt.ask("專案 ID（英數字，唯一）").strip()
    if not project_id:
        console.print("[red]ID 不可空白[/red]")
        return

    if get_project(project_id):
        console.print(f"[red]專案 {project_id!r} 已存在[/red]")
        return

    display_name = Prompt.ask("顯示名稱").strip()
    env_prefix = Prompt.ask("環境變數前綴（例如 NHAD）").strip().upper()
    version = Prompt.ask("版本號", default="1.0.0")
    validity_days = IntPrompt.ask("預設授權天數", default=365)

    create_project(
        id=project_id,
        display_name=display_name,
        env_prefix=env_prefix,
        version=version,
        validity_days=validity_days,
    )
    console.print(f"[green]✓ 專案 {project_id!r} 已建立[/green]")


def _list_projects() -> None:
    """Display all projects in a Rich table."""
    projects = list_projects()
    if not projects:
        console.print("[dim]尚無任何專案[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("名稱")
    table.add_column("環境變數前綴")
    table.add_column("版本")
    table.add_column("授權天數", justify="right")
    table.add_column("建立時間")

    for p in projects:
        table.add_row(
            p.id,
            p.display_name,
            p.env_prefix,
            p.version,
            str(p.validity_days),
            p.created_at.strftime("%Y-%m-%d"),
        )

    console.print(table)
