"""SDK export command — generates a deployable client_sdk/ for a specific project."""

import shutil
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt

from .db.crud import get_active_key, get_project

console = Console()

_REPO_ROOT = Path(__file__).parent.parent
_CLIENT_SDK = _REPO_ROOT / "client_sdk"
_DIST = _REPO_ROOT / "dist"


def cmd_export_menu() -> None:
    """Display the export sub-menu and dispatch commands."""
    while True:
        console.print("\n[bold cyan]── SDK 匯出 ──[/bold cyan]")
        console.print("  \\[e] 為專案匯出客戶端 SDK")
        console.print("  \\[b] 返回主選單")

        choice = Prompt.ask("選擇").strip().lower()

        if choice == "e":
            _export_sdk()
        elif choice == "b":
            return


def _export_sdk() -> None:
    """Copy client_sdk/ and inject the project's public key + env prefix."""
    project_id = Prompt.ask("專案 ID").strip()
    project = get_project(project_id)
    if not project:
        console.print(f"[red]找不到專案 {project_id!r}[/red]")
        return

    key = get_active_key(project_id)
    if not key:
        console.print("[red]此專案尚未產生金鑰，請先至金鑰管理產生金鑰。[/red]")
        return

    out_dir = _DIST / project_id
    if out_dir.exists():
        overwrite = Prompt.ask(f"{out_dir} 已存在，覆蓋？", choices=["y", "n"], default="y")
        if overwrite != "y":
            return
        shutil.rmtree(out_dir)

    shutil.copytree(_CLIENT_SDK, out_dir)

    # Inject public key and env prefix into the copy of verify_license.py
    verify_path = out_dir / "verify_license.py"
    content = verify_path.read_text(encoding="utf-8")

    pub_key_escaped = key.public_key_pem.strip().replace("\\", "\\\\")
    content = content.replace(
        'PUBLIC_KEY_PEM: bytes = b""  # filled in by: tools/main.py → [e] 匯出 SDK',
        f'PUBLIC_KEY_PEM: bytes = b"""{pub_key_escaped}"""',
    )
    content = content.replace(
        'ENV_PREFIX: str = "PROJ"    # filled in by: tools/main.py → [e] 匯出 SDK',
        f'ENV_PREFIX: str = "{project.env_prefix}"',
    )
    verify_path.write_text(content, encoding="utf-8")

    console.print(f"\n[green]✓ SDK 已匯出至 {out_dir}[/green]")
    console.print(f"  公鑰版本：v{key.version}")
    console.print(f"  環境變數前綴：{project.env_prefix}")
    console.print("\n[dim]將此資料夾交付甲方，或複製進目標專案後編譯。[/dim]")
    console.print(f"\n[bold]交付清單：[/bold]")
    for f in sorted(out_dir.iterdir()):
        console.print(f"  {f.name}")
