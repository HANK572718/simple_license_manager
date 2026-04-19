"""Key management commands for the master CLI."""

import hashlib
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from .db.crud import create_key, get_active_key, list_keys
from .ui import pick_project

console = Console()

_PROJECTS_DIR = Path(__file__).parent.parent / "projects"


def cmd_keys_menu() -> None:
    """Display the key management sub-menu and dispatch commands."""
    while True:
        console.print("\n[bold cyan]── 金鑰管理 ──[/bold cyan]")
        console.print("  \\[g] 為專案產生新金鑰對")
        console.print("  \\[s] 顯示公鑰內容（供嵌入 verify_license.py）")
        console.print("  \\[l] 列出金鑰版本")
        console.print("  \\[b] 返回主選單")

        choice = Prompt.ask("選擇").strip().lower()

        if choice == "g":
            _generate_key()
        elif choice == "s":
            _show_public_key()
        elif choice == "l":
            _list_keys()
        elif choice == "b":
            return


def _generate_key() -> None:
    """Generate a new RSA key pair for a project and persist to disk + DB."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    project_id, _ = pick_project()
    if not project_id:
        return

    existing = list_keys(project_id)
    next_version = (max((k.version for k in existing), default=0)) + 1

    key_dir = _PROJECTS_DIR / project_id / "keys"
    key_dir.mkdir(parents=True, exist_ok=True)

    priv_path = key_dir / f"private_key_v{next_version}.pem"
    pub_path = key_dir / f"public_key_v{next_version}.pem"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    priv_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path.write_bytes(pub_pem)

    pub_fp = hashlib.sha256(pub_pem).hexdigest()

    create_key(
        project_id=project_id,
        version=next_version,
        public_key_pem=pub_pem.decode(),
        public_key_fp=pub_fp,
        private_key_path=str(priv_path),
    )

    console.print(f"[green]✓ 金鑰 v{next_version} 已產生[/green]")
    console.print(f"  私鑰：{priv_path}")
    console.print(f"  公鑰：{pub_path}")
    console.print(f"  公鑰指紋（SHA-256）：{pub_fp}")


def _show_public_key() -> None:
    """Print the active public key PEM for embedding into verify_license.py."""
    project_id, _ = pick_project()
    if not project_id:
        return

    key = get_active_key(project_id)
    if not key:
        console.print("[red]此專案尚未產生任何金鑰[/red]")
        return

    console.print(f"\n[bold]v{key.version} 公鑰（貼入 verify_license.py 的 PUBLIC_KEY_PEM）：[/bold]")
    console.print(key.public_key_pem)


def _list_keys() -> None:
    """Show all keys for a project in a table."""
    project_id, _ = pick_project()
    if not project_id:
        return

    keys = list_keys(project_id)
    if not keys:
        console.print("[dim]此專案尚無金鑰[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("版本", justify="right")
    table.add_column("演算法")
    table.add_column("公鑰指紋（SHA-256）")
    table.add_column("建立時間")
    table.add_column("狀態")

    for k in keys:
        status = "[red]已退役[/red]" if k.retired_at else "[green]使用中[/green]"
        table.add_row(
            str(k.version),
            k.algorithm,
            k.public_key_fp[:16] + "...",
            k.created_at.strftime("%Y-%m-%d"),
            status,
        )

    console.print(table)
