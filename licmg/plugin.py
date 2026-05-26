"""Poetry ApplicationPlugin entry point for licmg.

Installation:
    Method A: poetry self add git+https://github.com/HANK572718/simple_license_manager.git
    Method B: git clone https://github.com/HANK572718/simple_license_manager.git
              poetry self add ./simple_license_manager

Usage (from the licmg project directory):
    poetry lm project create MY_PROJ "My Project" MYPROJ
    poetry lm project list
    poetry lm key generate MY_PROJ
    poetry lm key list MY_PROJ
    poetry lm license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
    poetry lm license list MY_PROJ
    poetry lm license export <id> --output /path/to/license.lic
    poetry lm license revoke <id>
    poetry lm sdk export MY_PROJ --output /path/to/dist
"""

from poetry.plugins.application_plugin import ApplicationPlugin

from licmg.commands.key import KeyGenerateCommand, KeyListCommand, KeyShowCommand
from licmg.commands.license import (
    LicenseExportCommand,
    LicenseIssueCommand,
    LicenseListCommand,
    LicenseRevokeCommand,
)
from licmg.commands.project import ProjectCreateCommand, ProjectListCommand
from licmg.commands.sdk import SdkExportCommand


# Thin wrappers that add the "lm " namespace prefix for Poetry plugin commands.
# The base command classes keep their short names for the standalone CLI.

class _LmProjectCreate(ProjectCreateCommand):
    name = "lm project create"

class _LmProjectList(ProjectListCommand):
    name = "lm project list"

class _LmKeyGenerate(KeyGenerateCommand):
    name = "lm key generate"

class _LmKeyList(KeyListCommand):
    name = "lm key list"

class _LmKeyShow(KeyShowCommand):
    name = "lm key show"

class _LmLicenseIssue(LicenseIssueCommand):
    name = "lm license issue"

class _LmLicenseList(LicenseListCommand):
    name = "lm license list"

class _LmLicenseExport(LicenseExportCommand):
    name = "lm license export"

class _LmLicenseRevoke(LicenseRevokeCommand):
    name = "lm license revoke"

class _LmSdkExport(SdkExportCommand):
    name = "lm sdk export"


class LicmgPlugin(ApplicationPlugin):
    """Poetry plugin that registers `poetry lm *` commands for license management."""

    def activate(self, application) -> None:  # type: ignore[override]
        """Register all lm-namespaced commands with Poetry's command loader."""
        commands = [
            _LmProjectCreate,
            _LmProjectList,
            _LmKeyGenerate,
            _LmKeyList,
            _LmKeyShow,
            _LmLicenseIssue,
            _LmLicenseList,
            _LmLicenseExport,
            _LmLicenseRevoke,
            _LmSdkExport,
        ]
        for cls in commands:
            application.command_loader.register_factory(cls.name, cls)
