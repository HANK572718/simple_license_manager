"""Cleo commands: project create / list."""

import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cleo.commands.command import Command
from cleo.helpers import argument, option

from rich_deploy.core.db.crud import create_project, get_project, list_projects
from rich_deploy.core.db.engine import init_db


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
    """Create a new project in the rich_deploy registry."""

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


class ProjectListCommand(Command):
    """List all projects in the rich_deploy registry."""

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
