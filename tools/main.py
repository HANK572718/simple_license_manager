"""Master CLI entry point for rich_deploy.

Usage:
    poetry run python tools/main.py
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so relative imports work when run directly.
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from tools.db.engine import init_db

console = Console()


def main() -> None:
    """Initialise the database and present the interactive main menu."""
    init_db()
    console.print(Panel(
        "[bold cyan]rich_deploy — 跨專案授權管理工具[/bold cyan]",
        subtitle="SQLite + RSA-2048 離線授權",
        expand=False,
    ))

    from tools.cmd_export import cmd_export_menu
    from tools.cmd_keys import cmd_keys_menu
    from tools.cmd_license import cmd_license_menu
    from tools.cmd_project import cmd_project_menu

    while True:
        console.print("\n[bold]主選單[/bold]")
        console.print("  \\[p] 專案管理")
        console.print("  \\[k] 金鑰管理")
        console.print("  \\[l] 授權管理")
        console.print("  \\[e] 匯出客戶端 SDK")
        console.print("  \\[q] 離開")

        choice = Prompt.ask("選擇").strip().lower()

        if choice == "p":
            cmd_project_menu()
        elif choice == "k":
            cmd_keys_menu()
        elif choice == "l":
            cmd_license_menu()
        elif choice == "e":
            cmd_export_menu()
        elif choice == "q":
            console.print("[dim]再見。[/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
