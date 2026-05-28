"""Cleo commands: license issue / list / export / revoke."""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmgr.core.db.crud import (
    create_license,
    get_active_key,
    get_license,
    get_project,
    list_licenses,
    revoke_license,
    update_license_file_path,
)
from licmgr.core.db.engine import init_db
from licmgr.core.sign_license import sign


class LicenseIssueCommand(Command):
    """Issue a new signed license for a project."""

    name = "license issue"
    description = "Issue a new signed license for a project"

    arguments = [
        argument("project-id", "Project identifier"),
        argument("fingerprint", "64-char hex machine fingerprint"),
    ]

    options = [
        option("--client", "-c", "Client / customer name", flag=False, default=""),
        option("--expires", "-e", "Expiry date YYYY-MM-DD (omit for perpetual)", flag=False, default=None),
        option("--mac", "-m", "MAC address hint for audit (not used in verification)", flag=False, default=None),
        option("--output", "-o", "Save .lic file to this path", flag=False, default=None),
        option(
            "--projects-dir",
            None,
            "Root directory for per-project key storage (default: ./projects)",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        fingerprint = self.argument("fingerprint")
        client_name = self.option("client") or "unnamed"
        expires_str: str | None = self.option("expires")
        mac_hint: str | None = self.option("mac")
        output_path_raw: str | None = self.option("output")

        project = get_project(project_id)
        if project is None:
            self.line_error(f"<error>Project '{project_id}' not found.</error>")
            return 1

        key = get_active_key(project_id)
        if key is None:
            self.line_error(
                f"<error>No active key for '{project_id}'. Run 'key generate {project_id}' first.</error>"
            )
            return 1

        priv_key_path = Path(key.private_key_path)
        if not priv_key_path.exists():
            self.line_error(f"<error>Private key not found: {priv_key_path}</error>")
            return 1

        try:
            lic_data = sign(
                fingerprint=fingerprint,
                expires=expires_str,
                mac_hint=mac_hint,
                note=client_name,
                fp_version=project.fp_version,
                private_key_path=priv_key_path,
            )
        except ValueError as exc:
            self.line_error(f"<error>{exc}</error>")
            return 1

        lic_json = json.dumps(lic_data, indent=2, ensure_ascii=False)

        # Determine where to save the .lic file
        save_path: str | None = None
        if output_path_raw:
            out = Path(output_path_raw)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(lic_json, encoding="utf-8")
            save_path = str(out)
            self.line(f"<info>License saved to {out}</info>")
        else:
            # Auto-save to CWD/projects/<project-id>/licenses/<client>.lic for easy delivery
            projects_dir_raw = self.option("projects-dir")
            projects_dir = Path(projects_dir_raw) if projects_dir_raw else Path.cwd() / "projects"
            lic_dir = projects_dir / project_id / "licenses"
            lic_dir.mkdir(parents=True, exist_ok=True)
            safe_name = client_name.replace(" ", "_").replace("/", "-")
            lic_file = lic_dir / f"{safe_name}.lic"
            lic_file.write_text(lic_json, encoding="utf-8")
            save_path = str(lic_file)
            self.line(f"<info>License saved to {lic_file}</info>")

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

        self.line("")
        self.line(lic_json)
        return 0


class LicenseListCommand(Command):
    """List all licenses for a project."""

    name = "license list"
    description = "List all licenses for a project"

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        licenses = list_licenses(project_id)

        if not licenses:
            self.line(f"<comment>No licenses found for '{project_id}'.</comment>")
            return 0

        console = Console()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", justify="right")
        table.add_column("Client")
        table.add_column("Fingerprint (first 16)")
        table.add_column("Key Ver", justify="right")
        table.add_column("Expires")
        table.add_column("Status")

        for lic in licenses:
            status = "[red]revoked[/red]" if lic.revoked else "[green]active[/green]"
            expires = lic.expires_at.strftime("%Y-%m-%d") if lic.expires_at else "perpetual"
            table.add_row(
                str(lic.id),
                lic.client_name,
                lic.machine_fp[:16] + "...",
                str(lic.key_version),
                expires,
                status,
            )

        console.print(table)
        return 0


class LicenseExportCommand(Command):
    """Export a license from the DB to a .lic file."""

    name = "license export"
    description = "Export a license record from the DB to a .lic file"

    arguments = [
        argument("license-id", "License record ID (see 'license list')"),
    ]

    options = [
        option("--output", "-o", "Output .lic file path", flag=False, default=None),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        try:
            license_id = int(self.argument("license-id"))
        except ValueError:
            self.line_error("<error>license-id must be an integer.</error>")
            return 1

        lic = get_license(license_id)
        if lic is None:
            self.line_error(f"<error>License #{license_id} not found.</error>")
            return 1

        output_raw = self.option("output")
        if output_raw:
            out = Path(output_raw)
        else:
            safe_name = lic.client_name.replace(" ", "_").replace("/", "-")
            out = Path.cwd() / f"{safe_name}.lic"

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(lic.license_json, encoding="utf-8")
        update_license_file_path(license_id, str(out))

        self.line(f"<info>License #{license_id} exported to {out}</info>")
        return 0


class LicenseRevokeCommand(Command):
    """Revoke a license by its DB ID."""

    name = "license revoke"
    description = "Mark a license as revoked in the registry"

    arguments = [
        argument("license-id", "License record ID (see 'license list')"),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        try:
            license_id = int(self.argument("license-id"))
        except ValueError:
            self.line_error("<error>license-id must be an integer.</error>")
            return 1

        if revoke_license(license_id):
            self.line(f"<info>License #{license_id} revoked.</info>")
            return 0
        else:
            self.line_error(f"<error>License #{license_id} not found.</error>")
            return 1


class LicenseDeleteCommand(Command):
    """Hard-delete a license record (distinct from revoke, which is a soft flag)."""

    name = "license delete"
    description = (
        "Hard-delete a license record and move its .lic file to ~/.licmgr/.trash/. "
        "Unlike 'license revoke', the DB row is permanently removed."
    )

    arguments = [
        argument("license-id", "License record ID (see 'license list')"),
    ]

    options = [
        option("--yes", "-y", "Skip the confirmation prompt (for CI/CD use)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        from licmgr.core import dbmaint
        from licmgr.core.db.engine import get_session

        init_db()
        try:
            license_id = int(self.argument("license-id"))
        except ValueError:
            self.line_error("<error>license-id must be an integer.</error>")
            return 1

        lic = get_license(license_id)
        if lic is None:
            self.line_error(f"<error>License #{license_id} not found.</error>")
            return 1

        self.line(f"License #{lic.id} — client={lic.client_name!r} project={lic.project_id}")
        self.line(f"  .lic file: {lic.lic_file_path or '(none recorded)'}")

        if not self.option("yes"):
            ok = self.confirm("Permanently delete this license?", default=False)
            if not ok:
                self.line("<comment>Aborted.</comment>")
                return 0

        with get_session() as s:
            report = dbmaint.delete_license_with_trash(s, license_id)
        if report is None:
            self.line_error(f"<error>License #{license_id} not found.</error>")
            return 1
        self.line(f"<info>License #{license_id} deleted.</info>")
        if report["trash_dir"]:
            self.line(f"  files moved → {report['trash_dir']}")
        return 0
