"""Bootstrap script — dual-mode launcher.

Developer mode  (private_key.pem detected): runs four verification scenarios
                to confirm the signing + verification pipeline works end-to-end.

Customer mode   (no private key):            interactive deployment wizard that
                collects the fingerprint, waits for the license file, verifies it,
                and optionally sets the environment variable.
"""

import base64
import json
import os
import platform
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

# ── Path resolution ───────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_TOOLS = _HERE.parent / "tools"
_PRIVATE_KEY = _TOOLS / "private_key.pem"
_PUBLIC_KEY = _TOOLS / "public_key.pem"


def _is_dev_machine() -> bool:
    return _PRIVATE_KEY.exists()


# ── Lazy imports from sibling modules ─────────────────────────────────────────

def _import_fingerprint():
    import importlib.util
    spec = importlib.util.spec_from_file_location("get_fingerprint", _HERE / "get_fingerprint.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _import_sign():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sign_license", _TOOLS / "sign_license.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── Developer simulation mode ─────────────────────────────────────────────────

def _run_dev_simulation() -> None:
    """Run four test scenarios and report pass/fail."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    console.print(Panel("[bold cyan]rich_deploy — 開發機模擬測試[/bold cyan]", expand=False))

    gf = _import_fingerprint()
    sign_mod = _import_sign()

    pub_pem = _PUBLIC_KEY.read_bytes()
    fp = gf.get_fingerprint()

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    results: list[tuple[str, bool, str]] = []

    def _make_lic(fingerprint=fp, expires=None, corrupt_sig=False, fp_version=1):
        lic = sign_mod.sign(fingerprint, expires=expires, fp_version=fp_version)
        if corrupt_sig:
            lic["signature"] = base64.b64encode(b"INVALID_SIG").decode()
        return lic

    def _import_verify():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_license", _HERE / "verify_license.py"
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.verify_license

    _vl = _import_verify()

    def _verify_from_dict(lic_dict: dict) -> bool:
        import contextlib, io
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".lic", delete=False, encoding="utf-8"
        ) as f:
            json.dump(lic_dict, f)
            tmp = Path(f.name)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return _vl(license_path=tmp, public_key_pem=pub_pem)
        finally:
            tmp.unlink(missing_ok=True)

    # Scenario 1 — normal valid license
    lic1 = _make_lic(expires=tomorrow)
    ok1 = _verify_from_dict(lic1)
    results.append(("[1/4] 正常授權驗證", ok1, "應通過" if ok1 else "⚠ 失敗"))

    # Scenario 2 — tampered fingerprint (gate 1)
    lic2 = _make_lic(expires=tomorrow)
    lic2["fingerprint"] = "a" * 64
    ok2 = not _verify_from_dict(lic2)
    results.append(("[2/4] 竄改指紋 → 關卡一攔截", ok2, "符合預期" if ok2 else "⚠ 未攔截"))

    # Scenario 3 — expired license (gate 2)
    lic3 = _make_lic(expires=yesterday)
    ok3 = not _verify_from_dict(lic3)
    results.append(("[3/4] 過期授權 → 關卡二攔截", ok3, "符合預期" if ok3 else "⚠ 未攔截"))

    # Scenario 4 — tampered signature (gate 3)
    lic4 = _make_lic(expires=tomorrow, corrupt_sig=True)
    ok4 = not _verify_from_dict(lic4)
    results.append(("[4/4] 竄改簽章 → 關卡三攔截", ok4, "符合預期" if ok4 else "⚠ 未攔截"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("測試項目", style="cyan")
    table.add_column("結果", justify="center")
    table.add_column("說明")

    all_pass = True
    for label, passed, msg in results:
        icon = "✓" if passed else "✗"
        colour = "green" if passed else "red"
        table.add_row(label, f"[{colour}]{icon}[/{colour}]", msg)
        if not passed:
            all_pass = False

    console.print(table)
    if all_pass:
        console.print("\n[bold green]全部 4 項測試通過 ✓[/bold green]")
    else:
        console.print("\n[bold red]有測試未通過，請檢查上方紅色項目。[/bold red]")
        sys.exit(1)


# ── Customer deployment wizard ────────────────────────────────────────────────

def _set_env_var(name: str, value: str) -> None:
    """Write the environment variable to the shell profile or registry."""
    system = platform.system()

    if system == "Windows":
        if len(value) > 1024:
            print(f"⚠ 路徑過長（{len(value)} 字元），超過 setx 1024 字元上限，請手動設定。")
            print(f"   {name}={value}")
            return
        os.system(f'setx {name} "{value}"')
        print(f"✓ 已寫入使用者環境變數（setx）：{name}={value}")
        print("  請重新開啟終端機後生效。")

    elif system in ("Linux", "Darwin"):
        shell = os.environ.get("SHELL", "")
        if "zsh" in shell:
            rc = Path.home() / (".zshrc" if system == "Linux" else ".zshrc")
        else:
            rc = Path.home() / (".bashrc" if system == "Linux" else ".bash_profile")

        line = f'export {name}="{value}"'
        content = rc.read_text(encoding="utf-8") if rc.exists() else ""
        if name in content:
            print(f"⚠ {rc} 中已存在 {name}，請手動確認或移除舊值後重新執行。")
            return
        with rc.open("a", encoding="utf-8") as f:
            f.write(f"\n# Added by rich_deploy bootstrap\n{line}\n")
        print(f"✓ 已寫入 {rc}：{line}")
        print("  請執行 `source {rc}` 或重新開啟終端機後生效。")

    else:
        print(f"⚠ 不支援的作業系統（{system}），請手動設定：{name}={value}")


def _run_customer_wizard() -> None:
    """Interactive deployment wizard for end-users."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt

    console = Console()
    console.print(Panel("[bold cyan]rich_deploy — 客戶端授權部署精靈[/bold cyan]", expand=False))

    gf = _import_fingerprint()

    # Step 1 — collect and display fingerprint
    console.print("\n[bold][步驟 1/4] 採集本機指紋[/bold]")
    fp = gf.get_fingerprint()
    mac = gf.get_mac_hint()
    console.print(f"\n[yellow]指紋（請複製傳給授權方）：[/yellow]\n{fp}")
    if mac:
        console.print(f"[dim]（MAC 參考：{mac}，不影響授權）[/dim]")

    # Step 2 — wait for license file
    console.print("\n[bold][步驟 2/4] 取得授權檔[/bold]")
    lic_path_str = Prompt.ask("請輸入 license.lic 的完整路徑", default="license.lic")
    lic_path = Path(lic_path_str)

    # Step 3 — verify
    console.print("\n[bold][步驟 3/4] 驗證授權[/bold]")
    pub_pem = b""
    pubkey_path = Prompt.ask("請輸入公鑰 PEM 路徑（若已嵌入程式碼請按 Enter 略過）", default="")
    if pubkey_path:
        pub_pem = Path(pubkey_path).read_bytes()

    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("verify_license", _HERE / "verify_license.py")
    _vmod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_vmod)  # type: ignore[union-attr]
    pem = pub_pem or _vmod.PUBLIC_KEY_PEM
    ok = _vmod.verify_license(license_path=lic_path, public_key_pem=pem)

    if not ok:
        console.print("[red]✗ 授權驗證失敗，請確認檔案是否正確或聯繫授權方。[/red]")
        sys.exit(1)

    console.print("[green]✓ 授權驗證通過！[/green]")

    # Step 4 — set environment variable
    console.print("\n[bold][步驟 4/4] 設定環境變數[/bold]")
    env_name = f"PROJ_LICENSE_FILE"
    console.print(f"建議設定環境變數 [cyan]{env_name}[/cyan] 指向授權檔路徑。")
    console.print("選項：")
    console.print("  [A] 自動寫入系統環境變數（建議）")
    console.print("  [B] 只顯示路徑，手動設定")
    console.print("  [C] 產生 .env 檔案")

    choice = Prompt.ask("請選擇", choices=["A", "B", "C", "a", "b", "c"], default="A").upper()

    abs_path = str(lic_path.resolve())
    if choice == "A":
        _set_env_var(env_name, abs_path)
    elif choice == "B":
        console.print(f"\n請手動設定：[cyan]{env_name}={abs_path}[/cyan]")
    else:
        env_file = Path(".env")
        with env_file.open("a", encoding="utf-8") as f:
            f.write(f"{env_name}={abs_path}\n")
        console.print(f"✓ 已寫入 [cyan]{env_file}[/cyan]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Auto-detect mode and run the appropriate flow."""
    if _is_dev_machine():
        _run_dev_simulation()
    else:
        _run_customer_wizard()


if __name__ == "__main__":
    main()
