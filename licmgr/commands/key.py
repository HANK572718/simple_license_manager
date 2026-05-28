"""Cleo commands: key generate / list / show."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmgr.core.db.crud import create_key, get_active_key, get_project, list_keys
from licmgr.core.db.engine import LICMGR_DATA_DIR, get_session, init_db
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


class KeyImportCommand(Command):
    """Import an existing private key, deriving its public key + DB rows."""

    name = "key import"
    description = (
        "Import an existing RSA private key: derive its public key and "
        "rebuild the keys (and if needed projects) registry rows"
    )

    arguments = [
        argument("project-id", "Project identifier"),
        argument("private-key-path", "Path to the existing private_key_vN.pem"),
    ]

    options = [
        option("--version", None, "Key version number (default: 1)",
               flag=False, default="1"),
        option("--env-prefix", None,
               "Env-var prefix for a NEW project (default: project id)",
               flag=False, default=None),
        option("--no-create-project", None,
               "Fail instead of creating the project if it is missing",
               flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        from licmgr.core.import_key import import_private_key

        init_db()

        project_id = self.argument("project-id")
        priv_path = self.argument("private-key-path")
        try:
            version = int(self.option("version"))
        except ValueError:
            self.line_error("<error>--version must be an integer.</error>")
            return 1

        try:
            with get_session() as s:
                summary = import_private_key(
                    s,
                    project_id,
                    priv_path,
                    version=version,
                    env_prefix=self.option("env-prefix"),
                    create_project=not self.option("no-create-project"),
                )
        except ValueError as exc:
            self.line_error(f"<error>{exc}</error>")
            return 1

        if summary["project_created"]:
            self.line(
                f"<info>Project '{project_id}' created "
                f"(env_prefix={summary['env_prefix']}).</info>"
            )
        self.line(
            f"<info>Key v{version} {summary['key_action']} for '{project_id}'.</info>"
        )
        self.line(f"  Public fp   : {summary['public_key_fp']}")
        if summary["public_key_path"]:
            self.line(f"  Public key  : {summary['public_key_path']}")
        self.line(
            "<comment>Derived public key is byte-identical to the original — "
            "previously-issued .lic files remain valid.</comment>"
        )
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
    """Print a project's public-key PEM (active by default; pass a version or --all for others)."""

    name = "key show"
    description = (
        "Print public-key PEM for a project. Default (no version): active "
        "(newest non-retired) key only. Pass a version positional to print a "
        "specific version, or --all to print every key version (incl. retired)."
    )

    # Positional 'version' is optional — cleo accepts an optional argument via
    # the `optional=True` keyword. Mirrors 'key delete <project-id> <version>'
    # except the version here is optional. Avoiding --version because Poetry/
    # cleo reserves that long option globally (--version, -v, -V).
    arguments = [
        argument("project-id", "Project identifier"),
        argument(
            "version",
            "Optional: key version to print (default: active key)",
            optional=True,
        ),
    ]

    options = [
        option(
            "--all", None,
            "Print every key version's public PEM (active + retired)",
            flag=True,
        ),
    ]

    def _print_key_block(self, key, project_id: str) -> None:
        """Render one key as a labelled PEM block (no private material involved)."""
        status = "retired" if key.retired_at else "active"
        self.line(
            f"<info>Key v{key.version} ({status}) for '{project_id}' — "
            f"fp={key.public_key_fp[:16]}...</info>"
        )
        self.line(key.public_key_pem)

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
        want_all = self.option("all")
        ver_arg = self.argument("version")

        if want_all and ver_arg:
            self.line_error("<error>Pass either a version argument or --all, not both.</error>")
            return 1

        keys = list_keys(project_id)
        if not keys:
            self.line_error(f"<error>No keys found for '{project_id}'.</error>")
            return 1

        if want_all:
            for k in keys:
                self._print_key_block(k, project_id)
            return 0

        if ver_arg is not None:
            try:
                want_ver = int(ver_arg)
            except ValueError:
                self.line_error("<error>version must be an integer.</error>")
                return 1
            target = next((k for k in keys if k.version == want_ver), None)
            if target is None:
                available = ", ".join(f"v{k.version}" for k in keys)
                self.line_error(
                    f"<error>Key v{want_ver} not found for '{project_id}'. "
                    f"Available: {available}.</error>"
                )
                return 1
            self._print_key_block(target, project_id)
            return 0

        # Default (no version, no --all): active key, with a hint when more versions exist.
        active = get_active_key(project_id)
        if active is None:
            self.line_error(
                f"<error>No active key found for '{project_id}' "
                f"(all {len(keys)} key version(s) are retired). "
                f"Pass a version (e.g. 'key show {project_id} 1') or --all "
                f"to print retired keys.</error>"
            )
            return 1
        self._print_key_block(active, project_id)
        if len(keys) > 1:
            self.line(
                f"<comment>Note: this project has {len(keys)} key versions. "
                f"Use --all to print every PEM, or 'key show {project_id} N' "
                f"for a specific one.</comment>"
            )
        return 0


class KeyDeleteCommand(Command):
    """Hard-delete a key version (cascades to all licenses signed by it)."""

    name = "key delete"
    description = (
        "Hard-delete a key version AND every license that was signed by it. "
        "Private/public key .pem files and dependent .lic files are moved to "
        "~/.licmgr/.trash/. Irreversible (file recovery requires mv from trash)."
    )

    arguments = [
        argument("project-id", "Project identifier"),
        argument("version", "Key version (integer; see 'key list')"),
    ]

    options = [
        option("--yes", "-y", "Skip the confirmation prompt (for CI/CD use)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        from sqlalchemy import select
        from licmgr.core import dbmaint
        from licmgr.core.db.engine import get_session
        from licmgr.core.db.models import Key, License

        init_db()
        project_id = self.argument("project-id")
        try:
            version = int(self.argument("version"))
        except ValueError:
            self.line_error("<error>version must be an integer.</error>")
            return 1

        # Pre-check: confirm key exists and report dependent licenses.
        with get_session() as s:
            key = s.execute(
                select(Key).where(Key.project_id == project_id, Key.version == version)
            ).scalar_one_or_none()
            if key is None:
                self.line_error(
                    f"<error>Key v{version} for '{project_id}' not found.</error>"
                )
                return 1
            dep = s.execute(
                select(License).where(
                    License.project_id == project_id,
                    License.key_version == version,
                )
            ).scalars().all()
            dep_count = len(dep)
            active_dep = sum(1 for lic in dep if not lic.revoked)

        self.line(f"Key v{version} ({key.algorithm}) of '{project_id}'")
        self.line(f"  private key file: {key.private_key_path or '(none recorded)'}")
        self.line(f"  dependent licenses: {dep_count} ({active_dep} active, {dep_count - active_dep} revoked)")
        if dep_count:
            self.line(
                "<comment>These dependent licenses will also be hard-deleted "
                "and their .lic files moved to trash.</comment>"
            )

        if not self.option("yes"):
            ok = self.confirm(
                f"Permanently delete key v{version} and {dep_count} license(s)?",
                default=False,
            )
            if not ok:
                self.line("<comment>Aborted.</comment>")
                return 0

        with get_session() as s:
            report = dbmaint.delete_key_with_trash(s, project_id, version)
        if report is None:
            self.line_error(
                f"<error>Key v{version} for '{project_id}' not found.</error>"
            )
            return 1
        self.line(
            f"<info>Key v{version} deleted "
            f"(licenses removed: {len(report['deleted_licenses'])}).</info>"
        )
        if report["trash_dir"]:
            self.line(f"  files moved → {report['trash_dir']}")
        return 0


class KeyRetireCommand(Command):
    """Soft-retire a key version (sets retired_at; reversible; no files touched)."""

    name = "key retire"
    description = (
        "Mark a key version as retired (sets retired_at to now). Reversible — "
        "no files are touched, no licenses are deleted. New 'key generate' calls "
        "will bump to the next version. Use this instead of 'key delete' when "
        "you want to roll a key forward but keep history intact."
    )

    arguments = [
        argument("project-id", "Project identifier"),
        argument("version", "Key version (integer; see 'key list')"),
    ]

    def handle(self) -> int:
        """Execute the command."""
        from licmgr.core import dbmaint
        from licmgr.core.db.engine import get_session

        init_db()
        project_id = self.argument("project-id")
        try:
            version = int(self.argument("version"))
        except ValueError:
            self.line_error("<error>version must be an integer.</error>")
            return 1

        with get_session() as s:
            ok = dbmaint.retire_key(s, project_id, version)
        if not ok:
            self.line_error(
                f"<error>Key v{version} for '{project_id}' not found, or already retired.</error>"
            )
            return 1
        self.line(f"<info>Key v{version} of '{project_id}' retired.</info>")
        return 0


class KeyVerifyCommand(Command):
    """Verify that a project's private key matches a public key / license."""

    name = "key verify"
    description = (
        "Verify a private key matches a public key, verify_license.py, or .lic file"
    )

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    options = [
        option("--key", None, "Private key .pem path (overrides DB lookup)",
               flag=False, default=None),
        option("--key-version", None,
               "Use the private key recorded for this version (default: active key)",
               flag=False, default=None),
        option("--verify-license", None, "verify_license.py file with embedded PUBLIC_KEY_PEM",
               flag=False, default=None),
        option("--pub", None, "Public key .pem path", flag=False, default=None),
        option("--lic", None, ".lic file to functionally verify the signature against",
               flag=False, default=None),
    ]

    def handle(self) -> int:
        """Execute the command."""
        import json

        from licmgr.core import keycheck

        init_db()

        project_id = self.argument("project-id")
        project = get_project(project_id)
        if project is None:
            self.line_error(f"<error>Project '{project_id}' not found.</error>")
            return 1

        # Resolve the private key. Three sources, in precedence order:
        #   --key <path>          → use this file directly (overrides DB)
        #   --key-version N       → use the .private_key_path recorded for v{N}
        #   (neither)             → use the active key (newest non-retired)
        key_opt = self.option("key")
        ver_opt = self.option("key-version")
        if key_opt and ver_opt:
            self.line_error("<error>--key and --key-version are mutually exclusive.</error>")
            return 1

        if key_opt:
            priv_path = Path(key_opt).expanduser()
        elif ver_opt is not None:
            try:
                want = int(ver_opt)
            except ValueError:
                self.line_error("<error>--key-version must be an integer.</error>")
                return 1
            keys = list_keys(project_id)
            picked = next((k for k in keys if k.version == want), None)
            if picked is None:
                available = ", ".join(f"v{k.version}" for k in keys) or "(none)"
                self.line_error(
                    f"<error>Key v{want} not found for '{project_id}'. "
                    f"Available: {available}.</error>"
                )
                return 1
            priv_path = Path(picked.private_key_path).expanduser()
        else:
            active = get_active_key(project_id)
            if active is None:
                self.line_error(f"<error>No active key for '{project_id}'.</error>")
                return 1
            priv_path = Path(active.private_key_path).expanduser()
            all_keys = list_keys(project_id)
            if len(all_keys) > 1:
                self.line(
                    f"<comment>Using active key v{active.version}; "
                    f"--key-version N selects a different version.</comment>"
                )
        if not priv_path.is_file():
            self.line_error(f"<error>Private key not found: {priv_path}</error>")
            return 1
        priv_pem = priv_path.read_bytes()

        # Resolve the comparison target (exactly one expected).
        vl = self.option("verify-license")
        pub = self.option("pub")
        lic = self.option("lic")
        supplied = [x for x in (vl, pub, lic) if x]
        if len(supplied) != 1:
            self.line_error(
                "<error>Provide exactly one of --verify-license / --pub / --lic.</error>"
            )
            return 1

        try:
            if vl:
                text = Path(vl).expanduser().read_text(encoding="utf-8")
                pub_pem = keycheck.parse_pubkey_from_verify_license(text)
                matched, reason = keycheck.verify_keypair(priv_pem, public_pem=pub_pem)
            elif pub:
                pub_pem = Path(pub).expanduser().read_bytes()
                matched, reason = keycheck.verify_keypair(priv_pem, public_pem=pub_pem)
            else:
                lic_data = json.loads(Path(lic).expanduser().read_text(encoding="utf-8"))
                matched, reason = keycheck.verify_keypair(priv_pem, lic=lic_data)
        except Exception as exc:  # noqa: BLE001
            self.line_error(f"<error>{exc}</error>")
            return 1

        if matched:
            self.line(f"<info>MATCH</info> — {reason}")
            return 0
        self.line_error(f"<error>NO MATCH</error> — {reason}")
        return 1
