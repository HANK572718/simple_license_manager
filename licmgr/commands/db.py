"""Cleo commands: db relink-keys / db export.

Thin wrappers over :mod:`licmgr.core.dbmaint`. All real logic lives in the core
module so it can be unit tested without Poetry/Cleo.
"""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmgr.core import dbmaint
from licmgr.core.db.engine import LICMGR_DATA_DIR, get_config, get_session, init_db


def _keys_dir() -> Path:
    """Return the configured key-storage root (mirrors the TUI helper)."""
    raw = get_config().get("storage", {}).get("keys_dir", "")
    return Path(raw).expanduser() if raw else LICMGR_DATA_DIR / "projects"


class DbRelinkKeysCommand(Command):
    """Scan key paths and (optionally) auto-repair missing private-key paths."""

    name = "db relink-keys"
    description = "Scan / auto-repair private-key paths in the registry"

    options = [
        option("--auto", None, "Auto-search the keys dir and relink missing paths",
               flag=True),
        option("--keys-dir", None, "Override the keys root to search (with --auto)",
               flag=False, default=None),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()
        keys_dir_raw = self.option("keys-dir")
        keys_dir = Path(keys_dir_raw).expanduser() if keys_dir_raw else _keys_dir()
        console = Console()

        with get_session() as s:
            rows = dbmaint.scan_key_paths(s)
            if not rows:
                self.line("<comment>No keys found.</comment>")
                return 0

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Project")
            table.add_column("Ver", justify="right")
            table.add_column("Private key path")
            table.add_column("Exists")
            for r in rows:
                table.add_row(
                    r["project_id"], str(r["version"]),
                    r["private_key_path"] or "—",
                    "[green]yes[/green]" if r["exists"] else "[red]no[/red]",
                )
            console.print(table)

            if not self.option("auto"):
                missing = sum(1 for r in rows if not r["exists"])
                if missing:
                    self.line(f"<comment>{missing} missing. Re-run with --auto to repair.</comment>")
                return 0

            report = dbmaint.auto_relink(s, keys_dir)

        for r in report["relinked"]:
            self.line(f"<info>relinked</info> {r['project_id']} v{r['version']} -> {r['new_path']}")
        for r in report["still_missing"]:
            self.line_error(
                f"<error>still missing</error> {r['project_id']} v{r['version']}"
            )
        if not report["relinked"] and not report["still_missing"]:
            self.line("<info>All key paths already valid.</info>")
        return 0


class DbExportCommand(Command):
    """Export selected projects + licenses into a portable bundle."""

    name = "db export"
    description = "Export selected projects/licenses to a portable bundle directory"

    arguments = [
        argument("out-dir", "Destination directory for the bundle"),
    ]

    options = [
        option("--project", None, "Project id to include (repeatable)",
               flag=False, default=None, multiple=True),
        option("--license", None, "License id to include (repeatable)",
               flag=False, default=None, multiple=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()
        project_ids = list(self.option("project") or [])
        if not project_ids:
            self.line_error("<error>At least one --project is required.</error>")
            return 1
        try:
            license_ids = [int(x) for x in (self.option("license") or [])]
        except ValueError:
            self.line_error("<error>--license values must be integers.</error>")
            return 1

        out_dir = Path(self.argument("out-dir")).expanduser()
        with get_session() as s:
            report = dbmaint.export_subset(s, project_ids, license_ids, out_dir)

        self.line(f"<info>Exported to:</info> {report['out_dir']}")
        self.line(f"  Projects : {', '.join(report['projects']) or '—'}")
        self.line(f"  Keys     : {report['keys_exported']} "
                  f"({len(report['copied_keys'])} private files copied)")
        self.line(f"  Licenses : {report['licenses_exported']}")
        for m in report["missing_key_files"]:
            self.line_error(f"<comment>missing key file:</comment> {m}")
        if report["skipped_licenses"]:
            self.line_error(
                f"<comment>skipped licenses (project not selected):</comment> "
                f"{report['skipped_licenses']}"
            )
        if report["missing_projects"]:
            self.line_error(
                f"<comment>unknown projects:</comment> {report['missing_projects']}"
            )
        return 0
