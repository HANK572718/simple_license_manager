"""Cleo commands: project create / list."""

import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmgr.core.db.crud import create_project, get_project, list_projects
from licmgr.core.db.engine import init_db


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def detect_git_context() -> dict[str, str | None]:
    """Detect git provenance from the current working directory.

    Returns a dict with keys: git_remote, project_root, git_user_name, git_user_email.
    All values may be None if git is not available or the cwd is not a repo.
    """
    remote = _run_git("remote", "get-url", "origin") or None
    root = _run_git("rev-parse", "--show-toplevel") or str(Path.cwd())
    user_name = _run_git("config", "user.name") or None
    user_email = _run_git("config", "user.email") or None
    return {
        "git_remote": remote,
        "project_root": root,
        "git_user_name": user_name,
        "git_user_email": user_email,
    }


class ProjectCreateCommand(Command):
    """Create a new project in the licmgr registry."""

    name = "project create"
    description = "Create a new project in the registry"

    arguments = [
        argument("id", "Unique project identifier (e.g. MY_PROJECT)"),
        argument("display-name", "Human-readable project name"),
        argument("env-prefix", "Environment variable prefix (e.g. MYPROJ)"),
    ]

    options = [
        option("--proj-version", None, "Project version string", flag=False, default="1.0.0"),
        option("--validity-days", None, "Default license validity in days", flag=False, default="365"),
        option("--no-git-detect", None, "Skip git context auto-detection", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("id")
        display_name = self.argument("display-name")
        env_prefix = self.argument("env-prefix").upper()

        try:
            validity_days = int(self.option("validity-days"))
        except ValueError:
            self.line_error("<error>--validity-days must be an integer</error>")
            return 1

        if get_project(project_id):
            self.line_error(f"<error>Project '{project_id}' already exists.</error>")
            return 1

        git_ctx: dict[str, str | None] = {}
        if not self.option("no-git-detect"):
            git_ctx = detect_git_context()
            if git_ctx.get("git_remote"):
                self.line(f"  Git remote  : {git_ctx['git_remote']}")
            if git_ctx.get("project_root"):
                self.line(f"  Project root: {git_ctx['project_root']}")
            if git_ctx.get("git_user_name"):
                self.line(f"  Git user    : {git_ctx['git_user_name']} <{git_ctx.get('git_user_email', '')}>")

        create_project(
            id=project_id,
            display_name=display_name,
            env_prefix=env_prefix,
            version=self.option("proj-version"),
            validity_days=validity_days,
            **git_ctx,
        )
        self.line(f"<info>Project '{project_id}' created.</info>")
        return 0


class ProjectDeleteCommand(Command):
    """Hard-delete a project — cascades to every key and license; nuclear option."""

    name = "project delete"
    description = (
        "PERMANENTLY delete a project, all of its keys, and all of its licenses. "
        "All .pem and .lic files are moved to ~/.licmgr/.trash/. By default, "
        "asks the operator to retype the project id; --yes skips that prompt for "
        "CI/CD use (the trash move still happens). Irreversible — file recovery "
        "requires mv from trash."
    )

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    options = [
        option("--yes", "-y", "Skip the typed-id confirmation (for CI/CD use)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        from licmgr.core import dbmaint
        from licmgr.core.db.crud import list_keys, list_licenses
        from licmgr.core.db.engine import get_session

        init_db()
        project_id = self.argument("project-id")
        project = get_project(project_id)
        if project is None:
            self.line_error(f"<error>Project '{project_id}' not found.</error>")
            return 1

        keys = list_keys(project_id)
        lics = list_licenses(project_id)
        self.line(f"Project '{project_id}' — {project.display_name}")
        self.line(f"  keys to be removed     : {len(keys)}")
        self.line(f"  licenses to be removed : {len(lics)}")
        self.line(
            "<comment>All .pem and .lic files for this project will be moved to "
            "~/.licmgr/.trash/.</comment>"
        )

        if not self.option("yes"):
            typed = self.ask(
                f"To confirm, retype the project id exactly ('{project_id}'):", ""
            )
            if typed != project_id:
                self.line_error("<error>Confirmation failed — id mismatch. Aborted.</error>")
                return 1

        with get_session() as s:
            report = dbmaint.delete_project_with_trash(s, project_id)
        if report is None:
            self.line_error(f"<error>Project '{project_id}' not found.</error>")
            return 1
        self.line(
            f"<info>Project '{project_id}' deleted — "
            f"{len(report['deleted_keys'])} key(s), "
            f"{len(report['deleted_licenses'])} license(s) removed.</info>"
        )
        if report["trash_dir"]:
            self.line(f"  files moved → {report['trash_dir']}")
        return 0


class ProjectListCommand(Command):
    """List all projects in the licmgr registry."""

    name = "project list"
    description = "List all registered projects"

    options = [
        option("--provenance", "-p", "Show git provenance columns (remote, owner)", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()
        projects = list_projects()

        if not projects:
            self.line("<comment>No projects found. Run 'project create' first.</comment>")
            return 0

        console = Console()
        verbose = self.option("provenance")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID")
        table.add_column("Display Name")
        table.add_column("Env Prefix")
        table.add_column("Version")
        table.add_column("Validity (days)", justify="right")
        table.add_column("Created")
        if verbose:
            table.add_column("Git Remote")
            table.add_column("Owner")

        for p in projects:
            row = [
                p.id,
                p.display_name,
                p.env_prefix,
                p.version,
                str(p.validity_days),
                p.created_at.strftime("%Y-%m-%d"),
            ]
            if verbose:
                row.append(p.git_remote or "—")
                owner = p.git_user_name or "—"
                if p.git_user_email:
                    owner += f" <{p.git_user_email}>"
                row.append(owner)
            table.add_row(*row)

        console.print(table)
        return 0
