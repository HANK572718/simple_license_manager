"""Interactive TUI entry point for licmgr.

Launch with:
    licmgr
"""

import json
import os
import stat as _stat
import sys
from datetime import datetime
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from licmgr.core.db import engine as _engine_mod
from licmgr.core.db.engine import (
    LICMGR_DATA_DIR,
    get_config,
    init_db,
    save_config,
)
from licmgr.core.db.crud import (
    create_key,
    create_license,
    create_project,
    get_active_key,
    get_license,
    get_project,
    list_keys,
    list_licenses,
    list_projects,
    revoke_license,
    update_license_file_path,
)
from licmgr.core.generate_keys import generate_key_pair
from licmgr.core.sign_license import sign
from licmgr.commands.project import detect_git_context
from licmgr.commands.sdk import _TEMPLATE_DIR, _ENV_PREFIX_PLACEHOLDER, _PUB_KEY_PLACEHOLDER

console = Console()

_BACK = "← 返回"
_CANCEL = "← 取消"


# ── Storage helpers ───────────────────────────────────────────────────────────

def _keys_dir() -> Path:
    """Return the root directory for key storage (from config or default)."""
    raw = get_config().get("storage", {}).get("keys_dir", "")
    return Path(raw).expanduser() if raw else LICMGR_DATA_DIR / "projects"


def _licenses_dir() -> Path:
    """Return the root directory for .lic file storage (from config or default)."""
    raw = get_config().get("storage", {}).get("licenses_dir", "")
    return Path(raw).expanduser() if raw else Path.cwd() / "projects"


# ── Project menu ──────────────────────────────────────────────────────────────

def _project_menu() -> None:
    """Interactive submenu for project management."""
    while True:
        action = questionary.select(
            "📁 專案管理",
            choices=["列出所有專案", "新增專案", _BACK],
        ).ask()
        if action is None or action == _BACK:
            return
        if action == "列出所有專案":
            _list_projects()
        elif action == "新增專案":
            _create_project_tui()


def _list_projects() -> None:
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。請選擇「新增專案」。[/yellow]")
        return
    t = Table(show_header=True, header_style="bold cyan", expand=False)
    t.add_column("ID")
    t.add_column("名稱")
    t.add_column("前綴")
    t.add_column("版本")
    t.add_column("有效天數", justify="right")
    t.add_column("建立日期")
    for p in projects:
        t.add_row(p.id, p.display_name, p.env_prefix, p.version,
                  str(p.validity_days), p.created_at.strftime("%Y-%m-%d"))
    console.print(t)


def _create_project_tui() -> None:
    pid = questionary.text("專案 ID（英文大寫，例 MY_PROJ）：").ask()
    if not pid:
        return
    pid = pid.upper()
    if get_project(pid):
        console.print(f"[red]專案 '{pid}' 已存在。[/red]")
        return
    name = questionary.text("顯示名稱：").ask()
    prefix = questionary.text("環境變數前綴（英文大寫）：").ask()
    if not name or not prefix:
        return
    version = questionary.text("版本號：", default="1.0.0").ask()
    days = questionary.text("授權有效天數：", default="365").ask()
    try:
        validity = int(days)
    except ValueError:
        console.print("[red]無效的天數。[/red]")
        return

    git_ctx = detect_git_context()
    if git_ctx.get("git_remote"):
        console.print(f"  [dim]Git remote : {git_ctx['git_remote']}[/dim]")

    create_project(
        id=pid,
        display_name=name,
        env_prefix=prefix.upper(),
        version=version,
        validity_days=validity,
        **git_ctx,
    )
    console.print(f"[green]✓ 專案 '{pid}' 已建立。[/green]")


# ── Key menu ──────────────────────────────────────────────────────────────────

def _key_menu() -> None:
    """Interactive submenu for key pair management."""
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。請先建立專案。[/yellow]")
        return
    pid = questionary.select(
        "🔑 金鑰管理 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask()
    if pid is None or pid == _BACK:
        return

    while True:
        action = questionary.select(
            f"🔑 金鑰管理 — {pid}",
            choices=["列出金鑰", "產生新金鑰對", "顯示公鑰 PEM", _BACK],
        ).ask()
        if action is None or action == _BACK:
            return
        if action == "列出金鑰":
            _list_keys_tui(pid)
        elif action == "產生新金鑰對":
            _generate_key_tui(pid)
        elif action == "顯示公鑰 PEM":
            _show_key_tui(pid)


def _list_keys_tui(project_id: str) -> None:
    keys = list_keys(project_id)
    if not keys:
        console.print("[yellow]尚無金鑰。請選擇「產生新金鑰對」。[/yellow]")
        return
    t = Table(show_header=True, header_style="bold cyan", expand=False)
    t.add_column("版本", justify="right")
    t.add_column("演算法")
    t.add_column("公鑰指紋（前 16 碼）")
    t.add_column("建立日期")
    t.add_column("狀態")
    for k in keys:
        status = "[red]已退役[/red]" if k.retired_at else "[green]使用中[/green]"
        t.add_row(str(k.version), k.algorithm, k.public_key_fp[:16] + "...",
                  k.created_at.strftime("%Y-%m-%d"), status)
    console.print(t)


def _generate_key_tui(project_id: str) -> None:
    existing = list_keys(project_id)
    version = (max((k.version for k in existing), default=0)) + 1
    key_dir = _keys_dir() / project_id / "keys"
    priv_path, pub_path, pub_pem, pub_fp = generate_key_pair(key_dir, version)

    if os.name != "nt":
        try:
            os.chmod(priv_path, _stat.S_IRUSR | _stat.S_IWUSR)
        except OSError:
            pass

    create_key(
        project_id=project_id,
        version=version,
        public_key_pem=pub_pem,
        public_key_fp=pub_fp,
        private_key_path=str(priv_path.resolve()),
    )
    console.print(f"[green]✓ 金鑰 v{version} 已產生。[/green]")
    console.print(f"  私鑰 : {priv_path}")
    console.print(f"  公鑰 : {pub_path}")
    console.print(f"  [dim]私鑰儲存於 {_keys_dir()} — 請勿 commit[/dim]")


def _show_key_tui(project_id: str) -> None:
    key = get_active_key(project_id)
    if key is None:
        console.print("[yellow]無可用金鑰。請先產生金鑰。[/yellow]")
        return
    console.print(f"[cyan]v{key.version} 公鑰 PEM（可安全公開）：[/cyan]")
    console.print(key.public_key_pem)


# ── License menu ──────────────────────────────────────────────────────────────

def _license_menu() -> None:
    """Interactive submenu for license management."""
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。請先建立專案。[/yellow]")
        return
    pid = questionary.select(
        "📄 授權管理 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask()
    if pid is None or pid == _BACK:
        return

    while True:
        action = questionary.select(
            f"📄 授權管理 — {pid}",
            choices=["列出授權", "簽發新授權", "撤銷授權", "匯出 .lic 檔", _BACK],
        ).ask()
        if action is None or action == _BACK:
            return
        if action == "列出授權":
            _list_licenses_tui(pid)
        elif action == "簽發新授權":
            _issue_license_tui(pid)
        elif action == "撤銷授權":
            _revoke_license_tui(pid)
        elif action == "匯出 .lic 檔":
            _export_license_tui(pid)


def _list_licenses_tui(project_id: str) -> None:
    lics = list_licenses(project_id)
    if not lics:
        console.print("[yellow]尚無授權紀錄。[/yellow]")
        return
    t = Table(show_header=True, header_style="bold cyan", expand=False)
    t.add_column("ID", justify="right")
    t.add_column("客戶")
    t.add_column("指紋（前 16 碼）")
    t.add_column("金鑰版本", justify="right")
    t.add_column("到期日")
    t.add_column("狀態")
    for lic in lics:
        status = "[red]已撤銷[/red]" if lic.revoked else "[green]有效[/green]"
        expires = lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else "永久"
        t.add_row(str(lic.id), lic.client_name, lic.machine_fp[:16] + "...",
                  str(lic.key_version), expires, status)
    console.print(t)


def _issue_license_tui(project_id: str) -> None:
    project = get_project(project_id)
    key = get_active_key(project_id)
    if key is None:
        console.print("[red]無可用金鑰。請先產生金鑰。[/red]")
        return
    priv_path = Path(key.private_key_path)
    if not priv_path.exists():
        console.print(f"[red]私鑰不存在：{priv_path}[/red]")
        return

    fp = questionary.text("機器指紋（64 字元 hex）：").ask()
    if not fp or len(fp) != 64:
        console.print("[red]指紋格式不正確（需 64 字元 hex）。[/red]")
        return
    client = questionary.text("客戶名稱：", default="unnamed").ask()
    expires = questionary.text("到期日 YYYY-MM-DD（留空 = 永久授權）：", default="").ask()
    mac = questionary.text("MAC 位址（審計用，可留空）：", default="").ask()

    try:
        lic_data = sign(
            fingerprint=fp,
            expires=expires or None,
            mac_hint=mac or None,
            note=client,
            fp_version=project.fp_version,
            private_key_path=priv_path,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    lic_json = json.dumps(lic_data, indent=2, ensure_ascii=False)

    lic_dir = _licenses_dir() / project_id / "licenses"
    lic_dir.mkdir(parents=True, exist_ok=True)
    safe_name = client.replace(" ", "_").replace("/", "-")
    lic_file = lic_dir / f"{safe_name}.lic"
    lic_file.write_text(lic_json, encoding="utf-8")

    expires_dt = datetime.fromisoformat(expires) if expires else None
    create_license(
        project_id=project_id,
        client_name=client,
        machine_fp=fp,
        key_version=key.version,
        license_json=lic_json,
        fp_version=project.fp_version,
        mac_hint=mac or None,
        expires_at=expires_dt,
        lic_file_path=str(lic_file),
    )
    console.print(f"\n[green]✓ 授權已簽發並儲存到：{lic_file}[/green]\n")
    console.print(lic_json)


def _revoke_license_tui(project_id: str) -> None:
    active = [l for l in list_licenses(project_id) if not l.revoked]
    if not active:
        console.print("[yellow]無可撤銷的授權。[/yellow]")
        return
    choices = [f"#{l.id}  {l.client_name}  ({l.machine_fp[:8]}...)" for l in active] + [_CANCEL]
    sel = questionary.select("選擇要撤銷的授權：", choices=choices).ask()
    if sel is None or sel == _CANCEL:
        return
    lic_id = int(sel.split("#")[1].split()[0])
    if revoke_license(lic_id):
        console.print(f"[green]✓ 授權 #{lic_id} 已撤銷。[/green]")


def _export_license_tui(project_id: str) -> None:
    lics = list_licenses(project_id)
    if not lics:
        console.print("[yellow]無授權紀錄。[/yellow]")
        return
    choices = [
        f"#{l.id}  {l.client_name}  ({'已撤銷' if l.revoked else '有效'})"
        for l in lics
    ] + [_CANCEL]
    sel = questionary.select("選擇要匯出的授權：", choices=choices).ask()
    if sel is None or sel == _CANCEL:
        return
    lic_id = int(sel.split("#")[1].split()[0])
    lic = get_license(lic_id)
    if lic is None:
        return
    safe_name = lic.client_name.replace(" ", "_").replace("/", "-")
    out = Path.cwd() / f"{safe_name}.lic"
    out.write_text(lic.license_json, encoding="utf-8")
    update_license_file_path(lic_id, str(out))
    console.print(f"[green]✓ 已匯出到：{out}[/green]")


# ── SDK menu ──────────────────────────────────────────────────────────────────

def _sdk_menu() -> None:
    """Interactive submenu for SDK export."""
    import shutil

    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。[/yellow]")
        return
    pid = questionary.select(
        "📦 SDK 匯出 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask()
    if pid is None or pid == _BACK:
        return

    project = get_project(pid)
    key = get_active_key(pid)
    if key is None:
        console.print("[red]無可用金鑰。請先產生金鑰。[/red]")
        return

    out_raw = questionary.text(f"輸出目錄（直接 Enter 使用預設 ./dist/{pid}）：", default="").ask()
    out_dir = Path(out_raw) if out_raw else Path.cwd() / "dist" / pid

    if not _TEMPLATE_DIR.exists():
        console.print(f"[red]模板目錄不存在：{_TEMPLATE_DIR}[/red]")
        return

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(_TEMPLATE_DIR, out_dir)

    verify_path = out_dir / "verify_license.py"
    content = verify_path.read_text(encoding="utf-8")
    pub_key_escaped = key.public_key_pem.strip().replace("\\", "\\\\")
    content = content.replace(_PUB_KEY_PLACEHOLDER, f'PUBLIC_KEY_PEM: bytes = b"""{pub_key_escaped}"""')
    content = content.replace(_ENV_PREFIX_PLACEHOLDER, f'ENV_PREFIX: str = "{project.env_prefix}"')
    verify_path.write_text(content, encoding="utf-8")

    console.print(f"[green]✓ SDK 已匯出到：{out_dir}[/green]")
    console.print(f"  公鑰版本 : v{key.version}")
    console.print(f"  環境前綴 : {project.env_prefix}")
    console.print("  [dim]將整個目錄交付給客戶即可。[/dim]")


# ── Settings menu ─────────────────────────────────────────────────────────────

def _settings_menu() -> None:
    """Interactive submenu for path and storage configuration."""
    while True:
        config = get_config()
        db_url = config.get("database", {}).get("url")
        keys_raw = config.get("storage", {}).get("keys_dir", "")
        lic_raw = config.get("storage", {}).get("licenses_dir", "")
        cfg_file = Path.cwd() / "licmgr.toml"

        default_db = f"sqlite:///{(LICMGR_DATA_DIR / 'registry.db').as_posix()}"
        default_keys = str(LICMGR_DATA_DIR / "projects")
        default_lic = str(Path.cwd() / "projects")

        console.print("\n[bold cyan]⚙  設定 — 儲存路徑[/bold cyan]")
        console.print(f"  DB 路徑        : [yellow]{db_url or default_db + ' [預設]'}[/yellow]")
        console.print(f"  金鑰根目錄     : [yellow]{keys_raw or default_keys + ' [預設]'}[/yellow]")
        console.print(f"  授權檔根目錄   : [yellow]{lic_raw or default_lic + ' [預設]'}[/yellow]")
        cfg_status = f"[green]存在[/green]" if cfg_file.exists() else "[dim]不存在（使用預設值）[/dim]"
        console.print(f"  設定檔 {cfg_file.name} : {cfg_status}")

        action = questionary.select(
            "設定選項：",
            choices=[
                "修改 DB 路徑（database.url）",
                "修改金鑰根目錄（storage.keys_dir）",
                "修改授權檔根目錄（storage.licenses_dir）",
                "儲存設定到 licmgr.toml",
                "重設為預設值（刪除 licmgr.toml）",
                _BACK,
            ],
        ).ask()

        if action is None or action == _BACK:
            return

        if "DB 路徑" in action:
            val = questionary.text(
                "DB URL（例：sqlite:///db/registry.db 或絕對路徑 sqlite:////home/user/reg.db）："
            ).ask()
            if val:
                config.setdefault("database", {})["url"] = val
                save_config(config)
                _engine_mod._engine = None  # force engine re-init on next call
                console.print("[green]✓ DB 路徑已更新，重新連線將使用新路徑。[/green]")

        elif "金鑰根目錄" in action:
            val = questionary.text(
                f"金鑰根目錄絕對路徑（預設：{default_keys}）："
            ).ask()
            if val:
                config.setdefault("storage", {})["keys_dir"] = val
                save_config(config)
                console.print("[green]✓ 金鑰根目錄已更新。[/green]")

        elif "授權檔根目錄" in action:
            val = questionary.text(
                f"授權檔根目錄路徑（預設：{default_lic}）："
            ).ask()
            if val:
                config.setdefault("storage", {})["licenses_dir"] = val
                save_config(config)
                console.print("[green]✓ 授權檔根目錄已更新。[/green]")

        elif "儲存設定" in action:
            save_config(config)
            console.print(f"[green]✓ 設定已儲存到 {cfg_file}[/green]")

        elif "重設" in action:
            if cfg_file.exists():
                cfg_file.unlink()
            _engine_mod._engine = None
            console.print("[green]✓ 已重設為預設值（licmgr.toml 已移除）。[/green]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Launch the licmgr interactive TUI."""
    init_db()
    console.print(Panel(
        "[bold cyan]licmgr — 離線授權管理工具[/bold cyan]\n"
        "[dim]RSA-2048 + SQLite  |  Apache 2.0[/dim]",
        expand=False,
    ))

    menu_items = {
        "📁  專案管理": _project_menu,
        "🔑  金鑰管理": _key_menu,
        "📄  授權管理": _license_menu,
        "📦  SDK 匯出": _sdk_menu,
        "⚙   設定": _settings_menu,
        "🚪  離開": None,
    }

    while True:
        choice = questionary.select("主選單", choices=list(menu_items.keys())).ask()
        if choice is None or choice == "🚪  離開":
            console.print("[dim]再見。[/dim]")
            sys.exit(0)
        fn = menu_items.get(choice)
        if fn:
            fn()
