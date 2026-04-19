"""License management commands for the master CLI."""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .db.crud import create_license, get_active_key, get_project, list_licenses, revoke_license
from .sign_license import sign

console = Console()

_PROJECTS_DIR = Path(__file__).parent.parent / "projects"


def cmd_license_menu() -> None:
    """Display the license management sub-menu and dispatch commands."""
    while True:
        console.print("\n[bold cyan]── 授權管理 ──[/bold cyan]")
        console.print("  \\[n] 簽發新授權")
        console.print("  \\[l] 列出授權記錄")
        console.print("  \\[r] 撤銷授權")
        console.print("  \\[b] 返回主選單")

        choice = Prompt.ask("選擇").strip().lower()

        if choice == "n":
            _issue_license()
        elif choice == "l":
            _list_licenses()
        elif choice == "r":
            _revoke_license()
        elif choice == "b":
            return


def _pick_project():
    """Prompt for a project ID and validate it exists."""
    project_id = Prompt.ask("專案 ID").strip()
    project = get_project(project_id)
    if not project:
        console.print(f"[red]找不到專案 {project_id!r}[/red]")
        return None, None
    return project_id, project


def _issue_license() -> None:
    """Interactive wizard to sign and record a new license."""
    project_id, project = _pick_project()
    if not project_id:
        return

    key = get_active_key(project_id)
    if not key:
        console.print("[red]此專案尚無金鑰，請先至金鑰管理產生金鑰。[/red]")
        return

    # Use the project-specific private key file
    priv_key_path = Path(key.private_key_path)
    if not priv_key_path.exists():
        console.print(f"[red]找不到私鑰：{priv_key_path}[/red]")
        return

    client_name = Prompt.ask("客戶名稱").strip()
    fingerprint = Prompt.ask("機器指紋（64 字元 hex）").strip()
    mac_hint = Prompt.ask("MAC 位址（審計用，可留空）", default="").strip() or None

    expires_str = Prompt.ask(
        f"到期日 YYYY-MM-DD（留空 = 永久，建議 {project.validity_days} 天）",
        default="",
    ).strip() or None

    # Temporarily patch the private key path used by sign_license
    import tools.sign_license as _sl
    original_path = _sl._PRIVATE_KEY_PATH
    _sl._PRIVATE_KEY_PATH = priv_key_path

    try:
        lic_data = sign(
            fingerprint=fingerprint,
            expires=expires_str,
            mac_hint=mac_hint,
            note=client_name,
            fp_version=project.fp_version,
        )
    finally:
        _sl._PRIVATE_KEY_PATH = original_path

    lic_json = json.dumps(lic_data, indent=2, ensure_ascii=False)

    # Display the license
    console.print("\n[bold]授權 JSON（請複製給客戶存成 license.lic）：[/bold]")
    console.print("=" * 60)
    console.print(lic_json)
    console.print("=" * 60)

    # Optionally save to file
    save_path: str | None = None
    if Confirm.ask("是否同時儲存為 .lic 檔案？"):
        lic_dir = _PROJECTS_DIR / project_id / "licenses"
        lic_dir.mkdir(parents=True, exist_ok=True)
        safe_name = client_name.replace(" ", "_").replace("/", "-")
        lic_file = lic_dir / f"{safe_name}.lic"
        lic_file.write_text(lic_json, encoding="utf-8")
        save_path = str(lic_file)
        console.print(f"[green]✓ 已儲存至 {lic_file}[/green]")

    # Record in DB
    expires_dt = datetime.fromisoformat(expires_str) if expires_str else None
    create_license(
        project_id=project_id,
        client_name=client_name,
        machine_fp=fingerprint,
        key_version=key.version,
        license_json=lic_json,
        fp_version=project.fp_version,
        mac_hint=mac_hint,
        expires_at=expires_dt,
        lic_file_path=save_path,
    )
    console.print("[green]✓ 授權記錄已存入資料庫[/green]")


def _list_licenses() -> None:
    """Display all licenses for a project."""
    project_id, _ = _pick_project()
    if not project_id:
        return

    licenses = list_licenses(project_id)
    if not licenses:
        console.print("[dim]此專案尚無授權記錄[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", justify="right")
    table.add_column("客戶")
    table.add_column("指紋（前 16）")
    table.add_column("金鑰版本", justify="right")
    table.add_column("到期日")
    table.add_column("狀態")

    for lic in licenses:
        status = "[red]已撤銷[/red]" if lic.revoked else "[green]有效[/green]"
        expires = lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else "永久"
        table.add_row(
            str(lic.id),
            lic.client_name,
            lic.machine_fp[:16] + "...",
            str(lic.key_version),
            expires,
            status,
        )

    console.print(table)


def _revoke_license() -> None:
    """Revoke a license by its DB id."""
    project_id, _ = _pick_project()
    if not project_id:
        return

    _list_licenses()
    try:
        license_id = int(Prompt.ask("輸入要撤銷的授權 ID").strip())
    except ValueError:
        console.print("[red]無效的 ID[/red]")
        return

    if not Confirm.ask(f"確認撤銷授權 #{license_id}？"):
        return

    if revoke_license(license_id):
        console.print(f"[green]✓ 授權 #{license_id} 已標記為撤銷[/green]")
    else:
        console.print(f"[red]找不到授權 #{license_id}[/red]")
