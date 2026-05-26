"""Cleo commands: key generate / list / show."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmgr.core.db.crud import create_key, get_active_key, get_project, list_keys
from licmgr.core.db.engine import LICMGR_DATA_DIR, init_db
from licmgr.core.generate_keys import generate_key_pair

# Private keys are stored under the global safe data directory by default.
# This path survives plugin reinstalls, git operations, and project moves.
_DEFAULT_KEYS_ROOT = LICMGR_DATA_DIR / "projects"


class KeyGenerateCommand(Command):
    """Generate a new RSA-2048 key pair for a project."""

    name = "key generate"
    description = "Generate a new RSA-2048 key pair for a project"

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    options = [
        option(
            "--keys-dir",
            None,
            "Override the root directory for key storage (default: ~/.licmgr/projects)",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        project = get_project(project_id)
        if project is None:
            self.line_error(f"<error>Project '{project_id}' not found.</error>")
            return 1

        keys_dir_raw = self.option("keys-dir")
        keys_root = Path(keys_dir_raw) if keys_dir_raw else _DEFAULT_KEYS_ROOT

        existing_keys = list_keys(project_id)
        next_version = (max((k.version for k in existing_keys), default=0)) + 1

        key_dir = keys_root / project_id / "keys"
        priv_path, pub_path, pub_pem, pub_fp = generate_key_pair(key_dir, next_version)

        # Restrict permissions on POSIX — private key should be owner-read only
        import os, stat as _stat
        if os.name != "nt":
            try:
                os.chmod(priv_path, _stat.S_IRUSR | _stat.S_IWUSR)
            except OSError:
                pass

        create_key(
            project_id=project_id,
            version=next_version,
            public_key_pem=pub_pem,
            public_key_fp=pub_fp,
            private_key_path=str(priv_path.resolve()),
        )

        self.line(f"<info>Key v{next_version} generated for '{project_id}'.</info>")
        self.line(f"  Private key : {priv_path}")
        self.line(f"  Public key  : {pub_path}")
        self.line(f"  Public fp   : {pub_fp[:16]}...")
        self.line("<comment>Private key stored in ~/.licmgr/ — never commit it.</comment>")
        return 0


class KeyListCommand(Command):
    """List all key versions for a project."""

    name = "key list"
    description = "List all key versions for a project"

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        keys = list_keys(project_id)

        if not keys:
            self.line(f"<comment>No keys found for '{project_id}'.</comment>")
            return 0

        console = Console()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Version", justify="right")
        table.add_column("Algorithm")
        table.add_column("Public Key Fingerprint (SHA-256)")
        table.add_column("Created")
        table.add_column("Status")

        for k in keys:
            status = "[red]retired[/red]" if k.retired_at else "[green]active[/green]"
            table.add_row(
                str(k.version),
                k.algorithm,
                k.public_key_fp[:32] + "...",
                k.created_at.strftime("%Y-%m-%d"),
                status,
            )

        console.print(table)
        return 0


class KeyShowCommand(Command):
    """Print the active public key PEM for a project."""

    name = "key show"
    description = "Print the active public key PEM for a project"

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        key = get_active_key(project_id)

        if key is None:
            self.line_error(f"<error>No active key found for '{project_id}'.</error>")
            return 1

        self.line(f"<info>Active key v{key.version} for '{project_id}':</info>")
        self.line(key.public_key_pem)
        return 0
