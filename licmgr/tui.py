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
from sqlalchemy import select

from licmgr.core.db.engine import (
    LICMGR_DATA_DIR,
    get_config,
    get_session,
    init_db,
    save_config,
)
from licmgr.core.db.models import Key, License, Project
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


def _ask(prompt_fn):
    """Wrap a questionary call; return None on Ctrl+C instead of raising."""
    try:
        return prompt_fn()
    except KeyboardInterrupt:
        return None


# ── Storage helpers ───────────────────────────────────────────────────────────

def _keys_dir() -> Path:
    """Return the root directory for key storage (from config or default)."""
    raw = get_config().get("storage", {}).get("keys_dir", "")
    return Path(raw).expanduser() if raw else LICMGR_DATA_DIR / "projects"


def _licenses_dir() -> Path:
    """Return the root directory for .lic file storage (from config or default)."""
    raw = get_config().get("storage", {}).get("licenses_dir", "")
    return Path(raw).expanduser() if raw else Path.cwd() / "projects"


# ── Entry overview ────────────────────────────────────────────────────────────

def _print_overview() -> None:
    """Print the registry-overview banner above the main menu.

    Called fresh on every main-menu iteration so the snapshot reflects state
    *after* returning from any submenu (delete, create, retire …). Shows
    aggregate counts and a compact per-project table; the critical signal is
    the per-project "private-key file exists?" column (DB may record a path
    whose file is gone, e.g. moved or deleted).

    Never shows raw key material — only public-key-fingerprint prefixes.
    """
    projects = list_projects()

    if not projects:
        console.print(Panel(
            "[dim]尚無任何專案。請從「📁  專案管理 → 新增專案」開始。[/dim]",
            title="[bold cyan]licmgr 總覽[/bold cyan]",
            expand=False,
        ))
        return

    # Aggregate counts — single pass per category.
    total_keys = 0
    total_keys_active = 0
    total_lics = 0
    total_lics_active = 0
    per_project: list[tuple] = []  # (project, keys, licenses)

    for p in projects:
        ks = list_keys(p.id)
        ls = list_licenses(p.id)
        total_keys += len(ks)
        total_keys_active += sum(1 for k in ks if k.retired_at is None)
        total_lics += len(ls)
        total_lics_active += sum(1 for lic in ls if not lic.revoked)
        per_project.append((p, ks, ls))

    summary = (
        f"專案數: [bold]{len(projects)}[/bold]   "
        f"金鑰數: [bold]{total_keys}[/bold] "
        f"(可用 [green]{total_keys_active}[/green] / "
        f"退役 [red]{total_keys - total_keys_active}[/red])   "
        f"授權數: [bold]{total_lics}[/bold] "
        f"(有效 [green]{total_lics_active}[/green] / "
        f"撤銷 [red]{total_lics - total_lics_active}[/red])"
    )
    console.print(Panel(summary, title="[bold cyan]licmgr 總覽[/bold cyan]", expand=False))

    t = Table(show_header=True, header_style="bold cyan", expand=False)
    t.add_column("專案", no_wrap=True)
    t.add_column("名稱", no_wrap=True)
    t.add_column("版本")
    t.add_column("金鑰", no_wrap=True)
    t.add_column("私鑰檔", no_wrap=True)
    t.add_column("公鑰指紋(前16)")
    t.add_column("授權", justify="right")
    t.add_column("建立日")

    for p, ks, ls in per_project:
        if not ks:
            key_col = "—"
            priv_col = "—"
            fp_col = "—"
        else:
            # Multi-line cells: one line per key version (list_keys already
            # returns newest first, so the active key sits at the top).
            key_lines: list[str] = []
            priv_lines: list[str] = []
            fp_lines: list[str] = []
            for k in ks:
                tag = (
                    "[dim](已退役)[/dim]" if k.retired_at
                    else "[green](使用中)[/green]"
                )
                key_lines.append(f"v{k.version} {tag}")

                priv_path = (
                    Path(k.private_key_path).expanduser()
                    if k.private_key_path else None
                )
                if priv_path and priv_path.is_file():
                    priv_lines.append("[green]✓ 存在[/green]")
                else:
                    priv_lines.append("[red]✗ 遺失[/red]")

                fp_lines.append(
                    (k.public_key_fp[:16] + "...") if k.public_key_fp else "—"
                )

            key_col = "\n".join(key_lines)
            priv_col = "\n".join(priv_lines)
            fp_col = "\n".join(fp_lines)

        active_lics = sum(1 for lic in ls if not lic.revoked)
        if not ls:
            lic_col = "0"
        else:
            lic_col = f"{len(ls)} ({active_lics}/{len(ls) - active_lics})"

        t.add_row(
            p.id,
            p.display_name or "—",
            p.version,
            key_col,
            priv_col,
            fp_col,
            lic_col,
            p.created_at.strftime("%Y-%m-%d"),
        )

    console.print(t)
    console.print()  # blank line before the menu prompt


# ── Project menu ──────────────────────────────────────────────────────────────

def _project_menu() -> None:
    """Interactive submenu for project management."""
    while True:
        action = _ask(lambda: questionary.select(
            "📁 專案管理",
            choices=["列出所有專案", "🔎  查看專案詳情", "新增專案", _BACK],
        ).ask())
        if action is None or action == _BACK:
            return
        if action == "列出所有專案":
            _list_projects()
        elif action == "🔎  查看專案詳情":
            _project_detail_tui()
        elif action == "新增專案":
            _create_project_tui()


def _project_detail_tui() -> None:
    """Drill-down view: pick a project then show its keys + licensed devices.

    Renders three blocks for the picked project:
      1. Metadata panel (id / name / version / env_prefix / fp_version /
         validity / created / optional git provenance).
      2. Keys table — every version with file-existence check, full(ish) public
         fingerprint, status. No private material printed.
      3. Licensed-devices table — every license row with the *full* machine
         fingerprint (64-hex), optional MAC hint, key version it was signed by,
         issued/expires dates, and active/revoked status. This is the
         "授權電腦的相關指紋設備資訊" surface.

    Read-only view; press any key to return to the project submenu.
    """
    project = _pick_project()
    if project is None:
        return

    # ── 1. Metadata panel ────────────────────────────────────────────────────
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", min_width=12)
    grid.add_column()
    grid.add_row("專案 ID", project.id)
    grid.add_row("名稱", project.display_name or "—")
    grid.add_row("版本", project.version)
    grid.add_row("環境前綴", project.env_prefix or "—")
    grid.add_row("指紋版本", str(project.fp_version))
    grid.add_row("有效天數", f"{project.validity_days} 天")
    grid.add_row("建立日", project.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    if project.git_remote:
        grid.add_row("Git remote", project.git_remote)
    if project.git_user_name or project.git_user_email:
        owner = project.git_user_name or "—"
        if project.git_user_email:
            owner += f" <{project.git_user_email}>"
        grid.add_row("建立者", owner)
    if project.project_root:
        grid.add_row("Project root", project.project_root)
    console.print(Panel(
        grid,
        title=f"[bold cyan]📁 專案詳情:{project.id}[/bold cyan]",
        expand=False,
    ))

    # ── 2. Keys table ────────────────────────────────────────────────────────
    keys = list_keys(project.id)
    if not keys:
        console.print("\n[dim]🔑 此專案尚無金鑰。[/dim]")
    else:
        active_count = sum(1 for k in keys if k.retired_at is None)
        console.print(
            f"\n[bold]🔑 金鑰 — 共 {len(keys)} 把"
            f"([green]{active_count}[/green] 使用中 / "
            f"[red]{len(keys) - active_count}[/red] 退役)[/bold]"
        )
        kt = Table(show_header=True, header_style="bold cyan", expand=False)
        kt.add_column("版本", justify="right")
        kt.add_column("演算法")
        kt.add_column("公鑰指紋(前 32)")
        kt.add_column("私鑰檔", no_wrap=True)
        kt.add_column("私鑰路徑", overflow="fold")
        kt.add_column("建立日", no_wrap=True)
        kt.add_column("狀態", no_wrap=True)
        for k in keys:
            priv_path = (
                Path(k.private_key_path).expanduser()
                if k.private_key_path else None
            )
            if priv_path and priv_path.is_file():
                priv_col = "[green]✓ 存在[/green]"
            else:
                priv_col = "[red]✗ 遺失[/red]"
            status = "[red]已退役[/red]" if k.retired_at else "[green]使用中[/green]"
            fp_disp = (k.public_key_fp[:32] + "...") if k.public_key_fp else "—"
            kt.add_row(
                str(k.version),
                k.algorithm,
                fp_disp,
                priv_col,
                k.private_key_path or "—",
                k.created_at.strftime("%Y-%m-%d"),
                status,
            )
        console.print(kt)

    # ── 3. Licensed devices table ───────────────────────────────────────────
    lics = list_licenses(project.id)
    if not lics:
        console.print("\n[dim]📄 此專案尚無授權紀錄。[/dim]")
    else:
        active_lics = sum(1 for lic in lics if not lic.revoked)
        console.print(
            f"\n[bold]📄 授權電腦 — 共 {len(lics)} 筆"
            f"([green]{active_lics}[/green] 有效 / "
            f"[red]{len(lics) - active_lics}[/red] 撤銷)[/bold]"
        )
        lt = Table(show_header=True, header_style="bold cyan", expand=False)
        lt.add_column("ID", justify="right")
        lt.add_column("客戶", no_wrap=True)
        lt.add_column("機器指紋(完整 64 hex)", overflow="fold")
        lt.add_column("Key 版本", justify="right")
        lt.add_column("簽發日", no_wrap=True)
        lt.add_column("到期日", no_wrap=True)
        lt.add_column("MAC 提示")
        lt.add_column("狀態", no_wrap=True)
        for lic in lics:
            status = "[red]已撤銷[/red]" if lic.revoked else "[green]有效[/green]"
            expires = (
                lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at
                else "[dim]永久[/dim]"
            )
            lt.add_row(
                str(lic.id),
                lic.client_name or "—",
                lic.machine_fp,  # 64-hex; rich folds long content per column width
                str(lic.key_version),
                lic.issued_at.strftime("%Y-%m-%d"),
                expires,
                lic.mac_hint or "[dim]—[/dim]",
                status,
            )
        console.print(lt)
        console.print(
            "[dim]提示:'Key 版本' 是簽發時使用的金鑰版本,"
            "對應上表「🔑 金鑰」。MAC 為審計提示,驗證時不使用。[/dim]"
        )

    _ask(lambda: questionary.press_any_key_to_continue("按任意鍵返回…").ask())


def _list_projects() -> None:
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。請選擇「新增專案」。[/yellow]")
        return
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("ID", no_wrap=True)
    t.add_column("名稱", no_wrap=True)
    t.add_column("前綴")
    t.add_column("版本")
    t.add_column("有效天數", justify="right")
    t.add_column("建立日期")
    for p in projects:
        t.add_row(p.id, p.display_name, p.env_prefix, p.version,
                  str(p.validity_days), p.created_at.strftime("%Y-%m-%d"))
    console.print(t)


def _create_project_tui() -> None:
    pid = _ask(lambda: questionary.text("專案 ID（英文大寫，例 MY_PROJ）：").ask())
    if not pid:
        return
    pid = pid.upper()
    if get_project(pid):
        console.print(f"[red]專案 '{pid}' 已存在。[/red]")
        return
    name = _ask(lambda: questionary.text("顯示名稱：").ask())
    prefix = _ask(lambda: questionary.text("環境變數前綴（英文大寫）：").ask())
    if not name or not prefix:
        return
    version = _ask(lambda: questionary.text("版本號：", default="1.0.0").ask())
    days = _ask(lambda: questionary.text("授權有效天數：", default="365").ask())
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
    pid = _ask(lambda: questionary.select(
        "🔑 金鑰管理 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask())
    if pid is None or pid == _BACK:
        return

    while True:
        action = _ask(lambda: questionary.select(
            f"🔑 金鑰管理 — {pid}",
            choices=["列出金鑰", "產生新金鑰對", "📥  導入既有私鑰",
                     "顯示公鑰 PEM", "🔗  驗證金鑰配對", _BACK],
        ).ask())
        if action is None or action == _BACK:
            return
        if action == "列出金鑰":
            _list_keys_tui(pid)
        elif action == "產生新金鑰對":
            _generate_key_tui(pid)
        elif action == "📥  導入既有私鑰":
            _import_key_tui()
        elif action == "顯示公鑰 PEM":
            _show_key_tui(pid)
        elif action == "🔗  驗證金鑰配對":
            _verify_keypair_tui(pid)


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


def _import_key_tui() -> None:
    """Import an existing private key: derive its public key and (re)build rows.

    Flow: ask the private-key path, then either pick an existing project or
    enter a NEW project id (prompting env_prefix and version). For an existing
    project that already stores a public key, warn if the derived public key
    differs from the stored one (which would mean the wrong private key).
    """
    from licmgr.core import import_key as _import_key

    raw = _ask(lambda: questionary.text("既有私鑰 .pem 路徑：").ask())
    if not raw:
        return
    priv_path = Path(raw).expanduser()
    if not priv_path.is_file():
        console.print(f"[red]找不到私鑰檔案：{priv_path}[/red]")
        return

    _NEW = "＋ 新增專案 ID"
    projects = list_projects()
    choices = [p.id for p in projects] + [_NEW, _CANCEL]
    target = _ask(lambda: questionary.select(
        "導入到哪個專案？", choices=choices,
    ).ask())
    if target is None or target == _CANCEL:
        return

    create_proj = False
    env_prefix: str | None = None
    version = 1
    if target == _NEW:
        pid = _ask(lambda: questionary.text("新專案 ID（英文大寫，例 MY_PROJ）：").ask())
        if not pid:
            return
        pid = pid.upper()
        if get_project(pid):
            console.print(f"[red]專案 '{pid}' 已存在，請改從清單選取。[/red]")
            return
        create_proj = True
        env_prefix = _ask(lambda: questionary.text(
            "環境變數前綴（驅動客戶端 <PREFIX>_LICENSE_FILE）：", default=pid,
        ).ask())
        if env_prefix:
            env_prefix = env_prefix.upper()
        ver_raw = _ask(lambda: questionary.text("金鑰版本：", default="1").ask())
        try:
            version = int(ver_raw)
        except (TypeError, ValueError):
            console.print("[red]無效的版本號。[/red]")
            return
    else:
        pid = target
        # Capture the stored public key (if any) to compare after import.
        prior = get_active_key(pid)
        if prior is not None:
            try:
                derived_pem, _ = _import_key.derive_public_material(priv_path.read_bytes())
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                return
            if derived_pem.strip() != (prior.public_key_pem or "").strip():
                console.print(
                    "[bold red]⚠ 警告：導出的公鑰與此專案既存的公鑰不同！[/bold red]"
                )
                console.print(
                    "[yellow]這很可能是錯誤的私鑰；繼續將覆寫資料庫中的公鑰紀錄。[/yellow]"
                )
                cont = _ask(lambda: questionary.confirm("仍要繼續？", default=False).ask())
                if not cont:
                    return

    try:
        with get_session() as s:
            summary = _import_key.import_private_key(
                s, pid, priv_path,
                version=version,
                env_prefix=env_prefix,
                create_project=create_proj,
            )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    if summary["project_created"]:
        console.print(
            f"[green]✓ 已建立專案 '{pid}'（env_prefix={summary['env_prefix']}）。[/green]"
        )
    verb = "已新增" if summary["key_action"] == "created" else "已更新"
    console.print(f"[green]✓ 金鑰 v{version} {verb}。[/green]")
    console.print(f"  公鑰指紋 : {summary['public_key_fp']}")
    if summary["public_key_path"]:
        console.print(f"  公鑰檔案 : {summary['public_key_path']}")
    console.print(
        "  [dim]導出的公鑰與原始公鑰位元組相同 — 先前簽發的 .lic 仍然有效。[/dim]"
    )


def _print_one_public_key(key) -> None:
    """Print one Key's public PEM with a labelled banner.

    Public key material is safe to display — only private keys are sensitive.
    """
    status_tag = (
        " [dim](已退役)[/dim]" if key.retired_at
        else " [green](使用中)[/green]"
    )
    console.print(
        f"\n[cyan]v{key.version} 公鑰 PEM{status_tag}  "
        f"指紋: {key.public_key_fp[:16]}...[/cyan]"
    )
    console.print(key.public_key_pem)


def _show_key_tui(project_id: str) -> None:
    """Show public key PEM(s).

    Behaviour:
      * 0 keys  → error message.
      * 1 key   → print directly (no extra prompt — preserves prior UX).
      * 2+ keys → show the keys table for context, then ask the user to pick
        a specific version *or* "show every version".
    """
    keys = list_keys(project_id)
    if not keys:
        console.print("[yellow]無可用金鑰。請先產生金鑰。[/yellow]")
        return
    if len(keys) == 1:
        _print_one_public_key(keys[0])
        return

    # Multiple keys: list-for-context, then pick.
    _list_keys_tui(project_id)
    choices = []
    for k in keys:
        tag = "[已退役]" if k.retired_at else "[使用中]"
        choices.append(questionary.Choice(
            f"v{k.version}  {tag}  fp={k.public_key_fp[:16]}...",
            value=k.version,
        ))
    choices.append(questionary.Choice("📃 顯示所有版本的公鑰", value="__all__"))
    # NOTE: questionary's Choice(value=None) silently falls back to the title
    # at pick time, so we must NOT use value=None for cancel — instead omit
    # value entirely and compare against the title string explicitly.
    choices.append(questionary.Choice(_CANCEL))

    pick = _ask(lambda: questionary.select(
        f"此專案有 {len(keys)} 個金鑰版本,選擇要顯示哪個公鑰:",
        choices=choices,
    ).ask())
    if pick in (None, _CANCEL):
        return
    if pick == "__all__":
        for k in keys:
            _print_one_public_key(k)
    else:
        target = next(k for k in keys if k.version == pick)
        _print_one_public_key(target)


def _verify_keypair_tui(default_project_id: str | None = None) -> None:
    """Verify that a private key matches a public key / license / verify_license.py.

    Lets the user choose a private-key source and a comparison target, then
    prints a clear MATCH / NO MATCH verdict with a one-line reason.
    """
    from licmgr.core import keycheck

    # ── 1. Private key source ──────────────────────────────────────────────
    src = _ask(lambda: questionary.select(
        "選擇「私鑰」來源：",
        choices=["從專案讀取（DB 紀錄的私鑰路徑）", "輸入 .pem 檔案路徑", _CANCEL],
    ).ask())
    if src is None or src == _CANCEL:
        return

    priv_pem: bytes | None = None
    chosen_pid: str | None = default_project_id

    if src.startswith("從專案"):
        projects = list_projects()
        if not projects:
            console.print("[yellow]尚無任何專案。[/yellow]")
            return
        choices = [p.id for p in projects] + [_CANCEL]
        default = default_project_id if default_project_id in [p.id for p in projects] else None
        pid = _ask(lambda: questionary.select(
            "選擇專案：", choices=choices, default=default
        ).ask())
        if pid is None or pid == _CANCEL:
            return
        chosen_pid = pid
        key = _pick_one_key(pid, "選擇驗證用的金鑰版本(私鑰):")
        if key is None:
            return
        priv_path = Path(key.private_key_path).expanduser()
        if not priv_path.is_file():
            console.print(f"[red]私鑰檔案不存在：{priv_path}[/red]")
            console.print("[dim]提示：可至「🔁  DB 維運 → 修復金鑰路徑」修正。[/dim]")
            return
        priv_pem = priv_path.read_bytes()
        console.print(f"[dim]私鑰來源(v{key.version}):{priv_path}[/dim]")
    else:
        raw = _ask(lambda: questionary.text("私鑰 .pem 路徑：").ask())
        if not raw:
            return
        priv_path = Path(raw).expanduser()
        if not priv_path.is_file():
            console.print(f"[red]找不到檔案：{priv_path}[/red]")
            return
        priv_pem = priv_path.read_bytes()

    # ── 2. Comparison target ───────────────────────────────────────────────
    target_choices = [
        "verify_license.py 檔案（解析內嵌 PUBLIC_KEY_PEM）",
        ".lic 授權檔（功能性驗章）",
        "貼上公鑰 PEM 內容",
        "公鑰 .pem 檔案路徑",
    ]
    if chosen_pid is not None:
        target_choices.append("與 DB 內此專案儲存的公鑰比對")
    target_choices.append(_CANCEL)

    tgt = _ask(lambda: questionary.select(
        "選擇「測試公鑰」比對來源：", choices=target_choices
    ).ask())
    if tgt is None or tgt == _CANCEL:
        return

    matched = False
    reason = ""
    try:
        if tgt.startswith("verify_license.py"):
            raw = _ask(lambda: questionary.text("verify_license.py 路徑：").ask())
            if not raw:
                return
            text = Path(raw).expanduser().read_text(encoding="utf-8")
            pub = keycheck.parse_pubkey_from_verify_license(text)
            matched, reason = keycheck.verify_keypair(priv_pem, public_pem=pub)

        elif tgt.startswith(".lic"):
            raw = _ask(lambda: questionary.text(".lic 檔案路徑：").ask())
            if not raw:
                return
            lic = json.loads(Path(raw).expanduser().read_text(encoding="utf-8"))
            matched, reason = keycheck.verify_keypair(priv_pem, lic=lic)

        elif tgt.startswith("貼上公鑰"):
            text = _ask(lambda: questionary.text(
                "貼上公鑰 PEM（多行；結束後按 Esc 再 Enter）：", multiline=True
            ).ask())
            if not text or not text.strip():
                return
            matched, reason = keycheck.verify_keypair(priv_pem, public_pem=text.encode())

        elif tgt.startswith("公鑰 .pem"):
            raw = _ask(lambda: questionary.text("公鑰 .pem 路徑：").ask())
            if not raw:
                return
            pub = Path(raw).expanduser().read_bytes()
            matched, reason = keycheck.verify_keypair(priv_pem, public_pem=pub)

        else:  # DB stored public key
            key = _pick_one_key(chosen_pid, "選擇要比對的 DB 公鑰版本:")
            if key is None:
                return
            console.print(f"[dim]DB 公鑰來源(v{key.version}):指紋 {key.public_key_fp[:16]}...[/dim]")
            matched, reason = keycheck.verify_keypair(
                priv_pem, public_pem=key.public_key_pem.encode()
            )
    except FileNotFoundError as e:
        console.print(f"[red]找不到檔案：{e}[/red]")
        return
    except Exception as e:  # noqa: BLE001 - surface any parse/load error to user
        console.print(f"[red]驗證失敗：{e}[/red]")
        return

    if matched:
        console.print(f"\n[bold green]✅ MATCH[/bold green] — {reason}\n")
    else:
        console.print(f"\n[bold red]❌ NO MATCH[/bold red] — {reason}\n")


# ── License menu ──────────────────────────────────────────────────────────────

def _license_menu() -> None:
    """Interactive submenu for license management."""
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。請先建立專案。[/yellow]")
        return
    pid = _ask(lambda: questionary.select(
        "📄 授權管理 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask())
    if pid is None or pid == _BACK:
        return

    while True:
        action = _ask(lambda: questionary.select(
            f"📄 授權管理 — {pid}",
            choices=["列出授權", "簽發新授權", "撤銷授權", "匯出 .lic 檔", _BACK],
        ).ask())
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
    key = _pick_one_key(project_id, "選擇要用來簽發此授權的金鑰版本:")
    if key is None:
        return
    # The picker returns ANY chosen key (incl. retired). Issuing under a retired
    # key is unusual — warn but allow, since the operator may have a reason
    # (e.g. re-issuing an old license for a replacement device).
    if key.retired_at is not None:
        warn_ok = _ask(lambda: questionary.confirm(
            f"v{key.version} 已退役,確定要用它簽發新授權?", default=False
        ).ask())
        if not warn_ok:
            return
    priv_path = Path(key.private_key_path)
    if not priv_path.exists():
        console.print(f"[red]私鑰不存在：{priv_path}[/red]")
        return

    fp = _ask(lambda: questionary.text("機器指紋（64 字元 hex）：").ask())
    if not fp or len(fp) != 64:
        console.print("[red]指紋格式不正確（需 64 字元 hex）。[/red]")
        return
    client = _ask(lambda: questionary.text("客戶名稱：", default="unnamed").ask())
    if client is None:
        return
    expires = _ask(lambda: questionary.text("到期日 YYYY-MM-DD（留空 = 永久授權）：", default="").ask())
    if expires is None:
        return
    mac = _ask(lambda: questionary.text("MAC 位址（審計用，可留空）：", default="").ask())

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
    console.print(f"\n[green]✓ 授權已簽發並儲存到：{lic_file.resolve()}[/green]\n")
    console.print(lic_json)


def _revoke_license_tui(project_id: str) -> None:
    active = [l for l in list_licenses(project_id) if not l.revoked]
    if not active:
        console.print("[yellow]無可撤銷的授權。[/yellow]")
        return
    choices = [f"#{l.id}  {l.client_name}  ({l.machine_fp[:8]}...)" for l in active] + [_CANCEL]
    sel = _ask(lambda: questionary.select("選擇要撤銷的授權：", choices=choices).ask())
    if not sel or sel == _CANCEL:
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
    sel = _ask(lambda: questionary.select("選擇要匯出的授權：", choices=choices).ask())
    if not sel or sel == _CANCEL:
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
    pid = _ask(lambda: questionary.select(
        "📦 SDK 匯出 — 選擇專案：",
        choices=[p.id for p in projects] + [_BACK],
    ).ask())
    if pid is None or pid == _BACK:
        return

    project = get_project(pid)
    key = _pick_one_key(pid, "選擇要嵌入 SDK 的公鑰版本:")
    if key is None:
        return
    # Embedding a retired key's public PEM is valid (e.g. shipping SDK for
    # legacy customers who still hold v1-signed .lic files), just unusual.
    if key.retired_at is not None:
        warn_ok = _ask(lambda: questionary.confirm(
            f"v{key.version} 已退役,確定要用它的公鑰匯出 SDK?",
            default=False,
        ).ask())
        if not warn_ok:
            return

    default_out = str((Path.cwd() / "dist" / pid).resolve())
    out_raw = _ask(lambda: questionary.text("輸出目錄：", default=default_out).ask())
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

    console.print(f"[green]✓ SDK 已匯出到：{out_dir.resolve()}[/green]")
    console.print(f"  公鑰版本 : v{key.version}")
    console.print(f"  環境前綴 : {project.env_prefix}")
    console.print("  [dim]將整個目錄交付給客戶即可。[/dim]")


# ── Import menu ───────────────────────────────────────────────────────────────

def _import_db() -> None:
    """Import projects, keys and licenses from another licmgr SQLite database."""
    import sqlite3

    src_raw = _ask(lambda: questionary.text("舊資料庫路徑（.db 檔案）：").ask())
    if not src_raw:
        return
    src_path = Path(src_raw).expanduser()
    if not src_path.exists():
        console.print(f"[red]找不到檔案：{src_path}[/red]")
        return

    try:
        src_conn = sqlite3.connect(str(src_path))
        src_conn.row_factory = sqlite3.Row
        proj_rows = src_conn.execute("SELECT * FROM projects").fetchall()
        key_rows  = src_conn.execute("SELECT * FROM keys").fetchall()
        lic_rows  = src_conn.execute("SELECT * FROM licenses").fetchall()
        src_conn.close()
    except Exception as e:
        console.print(f"[red]無法讀取資料庫（格式不相容）：{e}[/red]")
        return

    console.print(
        f"\n發現：[cyan]{len(proj_rows)}[/cyan] 個專案、"
        f"[cyan]{len(key_rows)}[/cyan] 筆金鑰、"
        f"[cyan]{len(lic_rows)}[/cyan] 筆授權"
    )
    confirm = _ask(lambda: questionary.confirm("確認匯入？", default=True).ask())
    if not confirm:
        return

    p_ok = p_skip = k_ok = k_skip = l_ok = l_skip = 0

    def _dt(val):
        return datetime.fromisoformat(val) if val else None

    with get_session() as sess:
        for row in proj_rows:
            if sess.get(Project, row["id"]):
                p_skip += 1
                continue
            sess.add(Project(
                id=row["id"],
                display_name=row["display_name"],
                env_prefix=row["env_prefix"],
                version=row["version"],
                fp_version=row["fp_version"],
                validity_days=row["validity_days"],
                created_at=_dt(row["created_at"]),
                git_remote=row["git_remote"],
                project_root=row["project_root"],
                git_user_name=row["git_user_name"],
                git_user_email=row["git_user_email"],
            ))
            p_ok += 1

        for row in key_rows:
            dup = sess.execute(
                select(Key).where(Key.project_id == row["project_id"], Key.version == row["version"])
            ).scalars().first()
            if dup:
                k_skip += 1
                continue
            sess.add(Key(
                project_id=row["project_id"],
                version=row["version"],
                algorithm=row["algorithm"],
                public_key_pem=row["public_key_pem"],
                public_key_fp=row["public_key_fp"],
                private_key_path=row["private_key_path"],
                created_at=_dt(row["created_at"]),
                retired_at=_dt(row["retired_at"]),
                notes=row["notes"],
            ))
            k_ok += 1

        for row in lic_rows:
            dup = sess.execute(
                select(License).where(
                    License.project_id == row["project_id"],
                    License.machine_fp  == row["machine_fp"],
                    License.issued_at   == _dt(row["issued_at"]),
                )
            ).scalars().first()
            if dup:
                l_skip += 1
                continue
            sess.add(License(
                project_id=row["project_id"],
                client_name=row["client_name"],
                machine_fp=row["machine_fp"],
                fp_version=row["fp_version"],
                key_version=row["key_version"],
                mac_hint=row["mac_hint"],
                issued_at=_dt(row["issued_at"]),
                expires_at=_dt(row["expires_at"]),
                license_json=row["license_json"],
                lic_file_path=row["lic_file_path"],
                revoked=bool(row["revoked"]),
                revoked_at=_dt(row["revoked_at"]),
                notes=row["notes"],
            ))
            l_ok += 1

    console.print("\n[green]✓ 匯入完成[/green]")
    console.print(f"  專案：{p_ok} 新增  {p_skip} 略過（已存在）")
    console.print(f"  金鑰：{k_ok} 新增  {k_skip} 略過（已存在）")
    console.print(f"  授權：{l_ok} 新增  {l_skip} 略過（已存在）")
    if k_ok:
        console.print("[dim]  提示：私鑰路徑仍指向原始位置，請確認金鑰檔案可存取。[/dim]")


# ── DB maintenance menu ─────────────────────────────────────────────────────

def _dbmaint_menu() -> None:
    """Submenu for DB maintenance: scan / relink key paths, selective export, delete."""
    while True:
        action = _ask(lambda: questionary.select(
            "🔁 DB 維運",
            choices=[
                "檢查金鑰路徑",
                "修復金鑰路徑",
                "選擇性匯出",
                "🗑  刪除（專案 / 金鑰 / 授權）",
                _BACK,
            ],
        ).ask())
        if action is None or action == _BACK:
            return
        if action == "檢查金鑰路徑":
            _dbmaint_scan()
        elif action == "修復金鑰路徑":
            _dbmaint_relink()
        elif action == "選擇性匯出":
            _dbmaint_export()
        elif action.startswith("🗑"):
            _dbmaint_delete_menu()


# ── DB 維運：刪除子選單 ───────────────────────────────────────────────────────

def _pick_one_key(project_id: str, prompt: str = "選擇要使用的金鑰版本:") -> Key | None:
    """Pick a single Key version for *project_id* — used wherever a multi-key
    project would otherwise silently default to ``get_active_key``.

    Behaviour:
      * 0 keys  → print an error and return None.
      * 1 key   → return it directly (no prompt; identical to old UX).
      * 2+ keys → render the keys table for context, then ``questionary.select``
        with every version (active first, with status + fp prefix) + cancel.

    Callers should always use this instead of ``get_active_key`` for any action
    that operates on a *specific* key (verify, SDK embed, license sign,
    show-pubkey, …). Returns ``None`` on cancel or no-keys.
    """
    keys = list_keys(project_id)
    if not keys:
        console.print(f"[red]專案 {project_id} 無可用金鑰。請先產生金鑰。[/red]")
        return None
    if len(keys) == 1:
        return keys[0]

    _list_keys_tui(project_id)
    # First entry is the newest (list_keys returns DESC by version) — typically
    # the active one, so it naturally becomes questionary's default highlight.
    choices: list = []
    for k in keys:
        tag = "[已退役]" if k.retired_at else "[使用中]"
        choices.append(questionary.Choice(
            f"v{k.version}  {tag}  fp={k.public_key_fp[:16]}...",
            value=k.version,
        ))
    choices.append(questionary.Choice(_CANCEL))

    pick = _ask(lambda: questionary.select(prompt, choices=choices).ask())
    if pick in (None, _CANCEL):
        return None
    return next(k for k in keys if k.version == pick)


def _pick_project() -> Project | None:
    """Shared helper: let the user pick one project from the registry.

    Returns the selected Project (with a refreshed read of related collections
    not done here — callers should re-fetch keys/licenses) or None on cancel.
    """
    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。[/yellow]")
        return None
    choices = [
        questionary.Choice(
            f"{p.id}  —  {p.display_name or '(無名稱)'}",
            value=p.id,
        )
        for p in projects
    ] + [questionary.Choice(_CANCEL)]
    pid = _ask(lambda: questionary.select("選擇專案：", choices=choices).ask())
    if pid in (None, _CANCEL):
        return None
    return next((p for p in projects if p.id == pid), None)


def _dbmaint_delete_menu() -> None:
    """Sub-submenu for destructive ops; checkbox confirms keep the user safe."""
    console.print(Panel(
        "[red]這些操作會永久變更 DB[/red]。檔案會搬到 [cyan]~/.licmgr/.trash/[/cyan],"
        "不會直接消失,可手動還原。",
        title="[red bold]🗑  刪除維運[/red bold]",
        expand=False,
    ))
    while True:
        action = _ask(lambda: questionary.select(
            "選擇刪除動作",
            choices=[
                "刪除授權紀錄  (License)",
                "退役金鑰版本  (Key.retired_at=now,可逆)",
                "刪除金鑰版本  (Key + cascade 其下所有 license)",
                "刪除專案      (Project + 全部下層,核彈級)",
                _BACK,
            ],
        ).ask())
        if action is None or action == _BACK:
            return
        if action.startswith("刪除授權"):
            _delete_license_tui()
        elif action.startswith("退役金鑰"):
            _retire_key_tui()
        elif action.startswith("刪除金鑰"):
            _delete_key_tui()
        elif action.startswith("刪除專案"):
            _delete_project_tui()


def _delete_license_tui() -> None:
    """TUI flow: pick project → pick license → confirm → hard delete + trash .lic."""
    from licmgr.core import dbmaint

    project = _pick_project()
    if project is None:
        return
    lics = list_licenses(project.id)
    if not lics:
        console.print(f"[yellow]'{project.id}' 尚無授權紀錄。[/yellow]")
        return
    _list_licenses_tui(project.id)

    choices = [
        questionary.Choice(
            f"#{lic.id}  {lic.client_name}  fp={lic.machine_fp[:16]}...  "
            f"key v{lic.key_version}  {'[已撤銷]' if lic.revoked else '[有效]'}",
            value=lic.id,
        )
        for lic in lics
    ] + [questionary.Choice(_CANCEL)]
    pick = _ask(lambda: questionary.select("選擇要硬刪的授權：", choices=choices).ask())
    if pick in (None, _CANCEL):
        return

    lic = next(lic for lic in lics if lic.id == pick)
    console.print(Panel(
        f"[bold red]即將永久刪除授權 #{lic.id}[/bold red]\n"
        f"專案: {lic.project_id}\n"
        f"客戶: {lic.client_name}\n"
        f"指紋: {lic.machine_fp}\n"
        f".lic 檔: {lic.lic_file_path or '(無紀錄)'}\n"
        f"[dim]註: 與「撤銷」不同,此動作會把 DB row 永久移除。[/dim]",
        title="[red]確認刪除[/red]",
        expand=False,
    ))
    confirm = _ask(lambda: questionary.confirm(
        "確認刪除?(.lic 檔將搬至 ~/.licmgr/.trash/)", default=False
    ).ask())
    if not confirm:
        return

    with get_session() as s:
        report = dbmaint.delete_license_with_trash(s, pick)
    if report is None:
        console.print("[red]找不到該授權。[/red]")
        return
    console.print(f"[green]✓ 已刪除授權 #{pick}。[/green]")
    if report["trash_dir"]:
        console.print(f"[dim]  檔案已搬移至:{report['trash_dir']}[/dim]")
    else:
        console.print("[dim]  (無 .lic 檔需要搬移)[/dim]")


def _retire_key_tui() -> None:
    """TUI flow: pick project → pick non-retired key → confirm → retire (soft)."""
    from licmgr.core import dbmaint

    project = _pick_project()
    if project is None:
        return
    keys = list_keys(project.id)
    active = [k for k in keys if k.retired_at is None]
    if not active:
        console.print(f"[yellow]'{project.id}' 沒有可退役的金鑰(全部都已退役)。[/yellow]")
        return
    _list_keys_tui(project.id)

    choices = [
        questionary.Choice(
            f"v{k.version}  fp={k.public_key_fp[:16]}...  "
            f"建立 {k.created_at.strftime('%Y-%m-%d')}",
            value=k.version,
        )
        for k in active
    ] + [questionary.Choice(_CANCEL)]
    pick = _ask(lambda: questionary.select("選擇要退役的金鑰版本：", choices=choices).ask())
    if pick in (None, _CANCEL):
        return

    confirm = _ask(lambda: questionary.confirm(
        f"確認退役 {project.id} v{pick}?(可逆,不刪檔)", default=True
    ).ask())
    if not confirm:
        return

    with get_session() as s:
        ok = dbmaint.retire_key(s, project.id, pick)
    if ok:
        console.print(f"[green]✓ {project.id} v{pick} 已退役(retired_at=now)。[/green]")
    else:
        console.print("[red]退役失敗(金鑰已退役或不存在)。[/red]")


def _delete_key_tui() -> None:
    """TUI flow: pick project → pick key → show dependent licenses → confirm → cascade delete."""
    from sqlalchemy import select as _select

    from licmgr.core import dbmaint

    project = _pick_project()
    if project is None:
        return
    keys = list_keys(project.id)
    if not keys:
        console.print(f"[yellow]'{project.id}' 尚無金鑰。[/yellow]")
        return
    _list_keys_tui(project.id)

    choices = [
        questionary.Choice(
            f"v{k.version}  fp={k.public_key_fp[:16]}...  "
            f"{'[退役]' if k.retired_at else '[使用中]'}  "
            f"建立 {k.created_at.strftime('%Y-%m-%d')}",
            value=k.version,
        )
        for k in keys
    ] + [questionary.Choice(_CANCEL)]
    pick = _ask(lambda: questionary.select("選擇要硬刪的金鑰版本：", choices=choices).ask())
    if pick in (None, _CANCEL):
        return

    key = next(k for k in keys if k.version == pick)
    # Look up dependent licenses (same project + key_version) ourselves so we can
    # show the cascade impact before asking for confirmation.
    with get_session() as s:
        dep = s.execute(_select(License).where(
            License.project_id == project.id,
            License.key_version == pick,
        )).scalars().all()
        active_dep = sum(1 for lic in dep if not lic.revoked)

    console.print(Panel(
        f"[bold red]即將永久刪除 {project.id} 的金鑰 v{pick}[/bold red]\n"
        f"私鑰檔: {key.private_key_path or '(無紀錄)'}\n"
        f"連動授權: [bold]{len(dep)}[/bold] 筆 "
        f"([green]{active_dep}[/green] 有效 / [red]{len(dep) - active_dep}[/red] 撤銷)\n"
        f"[dim]註: 所有 .pem / .lic 檔將搬至 ~/.licmgr/.trash/;DB row 全部硬刪。[/dim]\n"
        f"[dim]提示: 若只是要換金鑰,可改用「退役金鑰版本」(可逆,不刪檔)。[/dim]",
        title="[red]確認 cascade 刪除[/red]",
        expand=False,
    ))
    confirm = _ask(lambda: questionary.confirm(
        f"確認硬刪 {project.id} v{pick} 與其下 {len(dep)} 筆 license?",
        default=False,
    ).ask())
    if not confirm:
        return

    with get_session() as s:
        report = dbmaint.delete_key_with_trash(s, project.id, pick)
    if report is None:
        console.print("[red]找不到該金鑰。[/red]")
        return
    console.print(
        f"[green]✓ 已刪除 {project.id} v{pick} "
        f"(連動移除 {len(report['deleted_licenses'])} 筆 license)。[/green]"
    )
    if report["trash_dir"]:
        console.print(f"[dim]  檔案已搬移至:{report['trash_dir']}[/dim]")


def _delete_project_tui() -> None:
    """TUI flow: pick project → show impact → require typed-id confirmation → cascade delete."""
    from licmgr.core import dbmaint

    project = _pick_project()
    if project is None:
        return
    keys = list_keys(project.id)
    lics = list_licenses(project.id)

    console.print(Panel(
        f"[bold red]即將永久刪除整個專案 '{project.id}'[/bold red]\n"
        f"名稱: {project.display_name}\n"
        f"金鑰: [bold]{len(keys)}[/bold] 筆(會一起被硬刪)\n"
        f"授權: [bold]{len(lics)}[/bold] 筆(會一起被硬刪)\n"
        f"[dim]所有 .pem / .lic 檔將搬至 ~/.licmgr/.trash/(可手動還原)。[/dim]",
        title="[red bold]☢  Project 核彈級刪除[/red bold]",
        expand=False,
    ))
    typed = _ask(lambda: questionary.text(
        f"為了確認,請完整鍵入專案 ID('{project.id}'):"
    ).ask())
    if typed != project.id:
        console.print("[yellow]ID 不符,已取消。[/yellow]")
        return

    with get_session() as s:
        report = dbmaint.delete_project_with_trash(s, project.id)
    if report is None:
        console.print("[red]找不到該專案。[/red]")
        return
    console.print(
        f"[green]✓ 專案 '{project.id}' 已刪除 — "
        f"keys: {len(report['deleted_keys'])},licenses: {len(report['deleted_licenses'])}。[/green]"
    )
    if report["trash_dir"]:
        console.print(f"[dim]  檔案已搬移至:{report['trash_dir']}[/dim]")


def _dbmaint_scan() -> None:
    """Show a table of every key's private-key path and whether it exists."""
    from licmgr.core import dbmaint

    with get_session() as s:
        rows = dbmaint.scan_key_paths(s)
    if not rows:
        console.print("[yellow]尚無任何金鑰紀錄。[/yellow]")
        return
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("專案")
    t.add_column("版本", justify="right")
    t.add_column("私鑰路徑")
    t.add_column("狀態")
    for r in rows:
        status = "[green]✓ 存在[/green]" if r["exists"] else "[red]✗ 遺失[/red]"
        t.add_row(r["project_id"], str(r["version"]), r["private_key_path"] or "—", status)
    console.print(t)
    missing = [r for r in rows if not r["exists"]]
    if missing:
        console.print(f"[yellow]{len(missing)} 筆金鑰路徑遺失，可用「修復金鑰路徑」修正。[/yellow]")


def _dbmaint_relink() -> None:
    """Repair a key's private-key path: auto-search keys_dir or enter manually."""
    from licmgr.core import dbmaint

    with get_session() as s:
        rows = dbmaint.scan_key_paths(s)
    if not rows:
        console.print("[yellow]尚無任何金鑰紀錄。[/yellow]")
        return

    mode = _ask(lambda: questionary.select(
        "修復方式：",
        choices=[
            f"自動搜尋金鑰根目錄（{_keys_dir()}）並修復所有遺失項",
            "手動指定單筆金鑰路徑",
            _CANCEL,
        ],
    ).ask())
    if mode is None or mode == _CANCEL:
        return

    if mode.startswith("自動搜尋"):
        with get_session() as s:
            report = dbmaint.auto_relink(s, _keys_dir())
        if report["relinked"]:
            console.print("[green]✓ 已修復：[/green]")
            for r in report["relinked"]:
                console.print(f"  {r['project_id']} v{r['version']} → {r['new_path']}")
        else:
            console.print("[dim]沒有需要修復的項目（或找不到對應檔案）。[/dim]")
        if report["still_missing"]:
            console.print("[yellow]仍然遺失（找不到檔案）：[/yellow]")
            for r in report["still_missing"]:
                console.print(f"  {r['project_id']} v{r['version']}（原路徑 {r['old_path'] or '—'}）")
        return

    # Manual: pick a key then enter a new path.
    choices = [
        questionary.Choice(
            f"{r['project_id']} v{r['version']}  "
            f"[{'存在' if r['exists'] else '遺失'}]  {r['private_key_path'] or '—'}",
            value=(r["project_id"], r["version"]),
        )
        for r in rows
    ]
    choices.append(questionary.Choice(_CANCEL))
    picked = _ask(lambda: questionary.select("選擇要修復的金鑰：", choices=choices).ask())
    # questionary's Choice(value=None) falls back to the title string at pick
    # time, so cancel returns _CANCEL ("← 取消"), not None. Must guard both.
    if picked in (None, _CANCEL):
        return
    project_id, version = picked
    new_path = _ask(lambda: questionary.text("新的私鑰 .pem 路徑：").ask())
    if not new_path:
        return
    resolved = Path(new_path).expanduser()
    if not resolved.is_file():
        cont = _ask(lambda: questionary.confirm(
            f"檔案 {resolved} 目前不存在，仍要寫入此路徑？", default=False
        ).ask())
        if not cont:
            return
    with get_session() as s:
        ok = dbmaint.relink_key(s, project_id, version, str(resolved))
    if ok:
        console.print(f"[green]✓ 已更新 {project_id} v{version} 的私鑰路徑。[/green]")
    else:
        console.print("[red]找不到對應的金鑰紀錄。[/red]")


def _dbmaint_export() -> None:
    """Selectively export chosen projects + licenses into a portable bundle."""
    from licmgr.core import dbmaint

    projects = list_projects()
    if not projects:
        console.print("[yellow]尚無任何專案。[/yellow]")
        return

    pids = _ask(lambda: questionary.checkbox(
        "選擇要匯出的專案（空白鍵勾選）：",
        choices=[p.id for p in projects],
    ).ask())
    if not pids:
        console.print("[dim]未選擇任何專案，已取消。[/dim]")
        return

    # Offer licenses belonging to the chosen projects.
    lic_choices: list = []
    for pid in pids:
        for lic in list_licenses(pid):
            label = (
                f"#{lic.id} {pid} | {lic.client_name} | {lic.machine_fp[:12]}…"
                f"{' [已撤銷]' if lic.revoked else ''}"
            )
            lic_choices.append(questionary.Choice(label, value=lic.id))

    license_ids: list[int] = []
    if lic_choices:
        sel = _ask(lambda: questionary.checkbox(
            "選擇要包含的授權（可全不選）：", choices=lic_choices
        ).ask())
        license_ids = sel or []

    out_raw = _ask(lambda: questionary.text(
        "輸出目錄：", default=str(Path.cwd() / "licmgr_export")
    ).ask())
    if not out_raw:
        return
    out_dir = Path(out_raw).expanduser()

    with get_session() as s:
        report = dbmaint.export_subset(s, list(pids), license_ids, out_dir)

    console.print(f"\n[green]✓ 已匯出到：{report['out_dir']}[/green]")
    console.print(f"  專案：{', '.join(report['projects']) or '—'}")
    console.print(f"  金鑰：{report['keys_exported']} 筆（複製 {len(report['copied_keys'])} 個私鑰檔）")
    console.print(f"  授權：{report['licenses_exported']} 筆")
    if report["missing_key_files"]:
        console.print("[yellow]  注意：下列私鑰檔在磁碟上不存在，未一併複製：[/yellow]")
        for m in report["missing_key_files"]:
            console.print(f"    {m}")
    if report["skipped_licenses"]:
        console.print(f"[yellow]  略過（專案未選取）的授權 id：{report['skipped_licenses']}[/yellow]")
    if report["missing_projects"]:
        console.print(f"[yellow]  找不到的專案：{report['missing_projects']}[/yellow]")


# ── Help menu ─────────────────────────────────────────────────────────────────

def _help_menu() -> None:
    """Display a brief explanation of licmgr concepts and menu items."""
    console.print(Panel(
        "[bold cyan]licmgr — 功能說明[/bold cyan]",
        expand=False,
    ))
    console.print("""
[bold]核心概念[/bold]

  一個 [cyan]專案[/cyan] 對應一個你要保護的軟體。
  每個專案持有一把 [yellow]RSA 金鑰對[/yellow]（私鑰簽發 / 公鑰驗證），
  並可為多台客戶機器各自簽發一份 [green]授權[/green]。

  [dim]專案  1 : 1  金鑰對[/dim]
  [dim]專案  1 : N  授權（每台機器一份）[/dim]

[bold]主選單功能[/bold]

  [cyan]📁 專案管理[/cyan]
      建立或列出你管理的軟體專案。
      每個專案有唯一 ID（如 MY_PROJ）、名稱與環境變數前綴。

  [yellow]🔑 金鑰管理[/yellow]
      為專案產生 RSA-2048 金鑰對。
        私鑰 → 存於 ~/.licmgr/，永不離開本機
        公鑰 → 嵌入 SDK，交給客戶用來驗證授權真偽
      同一把私鑰可簽發給任意多台機器，不需重新生成。

  [green]📄 授權管理[/green]
      為每台客戶機器簽發獨立的 .lic 授權檔。
      每份授權綁定一個機器指紋（64 字元 hex），換機即失效。
      可簽發 / 列出 / 撤銷 / 重新匯出 .lic 檔。

  [blue]📦 SDK 匯出[/blue]
      匯出整合包（公鑰已嵌入的 verify_license.py），
      直接交付給客戶整合進其應用程式。

  [dim]📥 匯入舊資料庫[/dim]
      從另一個 licmgr SQLite 資料庫匯入舊紀錄，跳過重複項目。

  [dim]⚙  設定[/dim]
      修改 DB 路徑、金鑰目錄、授權檔目錄；設定寫入 licmgr.toml。
""")
    _ask(lambda: questionary.press_any_key_to_continue("按任意鍵返回…").ask())


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

        action = _ask(lambda: questionary.select(
            "設定選項：",
            choices=[
                "修改 DB 路徑（database.url）",
                "修改金鑰根目錄（storage.keys_dir）",
                "修改授權檔根目錄（storage.licenses_dir）",
                "儲存設定到 licmgr.toml",
                "重設為預設值（刪除 licmgr.toml）",
                _BACK,
            ],
        ).ask())

        if action is None or action == _BACK:
            return

        if "DB 路徑" in action:
            val = _ask(lambda: questionary.text(
                "DB URL（例：sqlite:///db/registry.db 或絕對路徑 sqlite:////home/user/reg.db）："
            ).ask())
            if val:
                config.setdefault("database", {})["url"] = val
                save_config(config)
                _engine_mod._engine = None  # force engine re-init on next call
                console.print("[green]✓ DB 路徑已更新，重新連線將使用新路徑。[/green]")

        elif "金鑰根目錄" in action:
            val = _ask(lambda: questionary.text(
                f"金鑰根目錄絕對路徑（預設：{default_keys}）："
            ).ask())
            if val:
                config.setdefault("storage", {})["keys_dir"] = val
                save_config(config)
                console.print("[green]✓ 金鑰根目錄已更新。[/green]")

        elif "授權檔根目錄" in action:
            val = _ask(lambda: questionary.text(
                f"授權檔根目錄路徑（預設：{default_lic}）："
            ).ask())
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
        "📥  匯入舊資料庫": _import_db,
        "🔁  DB 維運": _dbmaint_menu,
        "⚙   設定": _settings_menu,
        "❓  說明": _help_menu,
        "🚪  離開": None,
    }

    try:
        while True:
            # Overview re-renders every iteration so it reflects the latest state
            # after returning from any submenu (create, delete, retire, …).
            _print_overview()
            choice = _ask(lambda: questionary.select("主選單", choices=list(menu_items.keys())).ask())
            if choice is None or choice == "🚪  離開":
                console.print("[dim]再見。[/dim]")
                sys.exit(0)
            fn = menu_items.get(choice)
            if fn:
                fn()
    except KeyboardInterrupt:
        console.print("\n[dim]已中斷。[/dim]")
        sys.exit(0)
