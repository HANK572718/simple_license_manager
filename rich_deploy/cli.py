"""Standalone CLI entry point for rich-deploy.

Usage after install (pip install rich-deploy / poetry add rich-deploy):
    rich-deploy project create MY_PROJ "My Project" MYPROJ
    rich-deploy project list
    rich-deploy key generate MY_PROJ
    rich-deploy key list MY_PROJ
    rich-deploy key show MY_PROJ
    rich-deploy license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
    rich-deploy license list MY_PROJ
    rich-deploy license export <id> --output /path/to/license.lic
    rich-deploy license revoke <id>
    rich-deploy sdk export MY_PROJ --output /path/to/dist
"""

from cleo.application import Application

from rich_deploy import __version__
from rich_deploy.commands.key import KeyGenerateCommand, KeyListCommand, KeyShowCommand
from rich_deploy.commands.license import (
    LicenseExportCommand,
    LicenseIssueCommand,
    LicenseListCommand,
    LicenseRevokeCommand,
)
from rich_deploy.commands.project import ProjectCreateCommand, ProjectListCommand
from rich_deploy.commands.sdk import SdkExportCommand


def main() -> None:
    """Entry point for the `rich-deploy` CLI."""
    app = Application("rich-deploy", __version__)
    app.add(ProjectCreateCommand())
    app.add(ProjectListCommand())
    app.add(KeyGenerateCommand())
    app.add(KeyListCommand())
    app.add(KeyShowCommand())
    app.add(LicenseIssueCommand())
    app.add(LicenseListCommand())
    app.add(LicenseExportCommand())
    app.add(LicenseRevokeCommand())
    app.add(SdkExportCommand())
    app.run()


if __name__ == "__main__":
    main()
