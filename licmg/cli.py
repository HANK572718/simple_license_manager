"""Standalone CLI entry point for licmg.

Usage after install (pip install licmg / poetry add licmg):
    licmg project create MY_PROJ "My Project" MYPROJ
    licmg project list
    licmg key generate MY_PROJ
    licmg key list MY_PROJ
    licmg key show MY_PROJ
    licmg license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
    licmg license list MY_PROJ
    licmg license export <id> --output /path/to/license.lic
    licmg license revoke <id>
    licmg sdk export MY_PROJ --output /path/to/dist
"""

from cleo.application import Application

from licmg import __version__
from licmg.commands.key import KeyGenerateCommand, KeyListCommand, KeyShowCommand
from licmg.commands.license import (
    LicenseExportCommand,
    LicenseIssueCommand,
    LicenseListCommand,
    LicenseRevokeCommand,
)
from licmg.commands.project import ProjectCreateCommand, ProjectListCommand
from licmg.commands.sdk import SdkExportCommand


def main() -> None:
    """Entry point for the 'licmg' CLI."""
    app = Application("licmg", __version__)
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
