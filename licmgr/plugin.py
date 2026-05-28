"""Poetry ApplicationPlugin entry point for licmgr.

Installation:
    Method A: poetry self add git+https://github.com/HANK572718/simple_license_manager.git
    Method B: git clone https://github.com/HANK572718/simple_license_manager.git
              poetry self add ./simple_license_manager

Usage (from the licmgr project directory):
    poetry licmgr project create MY_PROJ "My Project" MYPROJ
    poetry licmgr project list
    poetry licmgr key generate MY_PROJ
    poetry licmgr key list MY_PROJ
    poetry licmgr license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
    poetry licmgr license list MY_PROJ
    poetry licmgr license export <id> --output /path/to/license.lic
    poetry licmgr license revoke <id>
    poetry licmgr sdk export MY_PROJ --output /path/to/dist
"""

from cleo.commands.command import Command
from poetry.plugins.application_plugin import ApplicationPlugin

from licmgr.commands.db import DbExportCommand, DbRelinkKeysCommand
from licmgr.commands.key import (
    KeyDeleteCommand,
    KeyGenerateCommand,
    KeyImportCommand,
    KeyListCommand,
    KeyRetireCommand,
    KeyShowCommand,
    KeyVerifyCommand,
)
from licmgr.commands.license import (
    LicenseDeleteCommand,
    LicenseExportCommand,
    LicenseIssueCommand,
    LicenseListCommand,
    LicenseRevokeCommand,
)
from licmgr.commands.project import (
    ProjectCreateCommand,
    ProjectDeleteCommand,
    ProjectListCommand,
)
from licmgr.commands.sdk import SdkExportCommand


# Thin wrappers that add the "licmgr " namespace prefix for Poetry plugin commands.
# The base command classes keep their short names for the standalone CLI.

class _LicmgrProjectCreate(ProjectCreateCommand):
    name = "licmgr project create"

class _LicmgrProjectList(ProjectListCommand):
    name = "licmgr project list"

class _LicmgrProjectDelete(ProjectDeleteCommand):
    name = "licmgr project delete"

class _LicmgrKeyGenerate(KeyGenerateCommand):
    name = "licmgr key generate"

class _LicmgrKeyImport(KeyImportCommand):
    name = "licmgr key import"

class _LicmgrKeyList(KeyListCommand):
    name = "licmgr key list"

class _LicmgrKeyShow(KeyShowCommand):
    name = "licmgr key show"

class _LicmgrKeyVerify(KeyVerifyCommand):
    name = "licmgr key verify"

class _LicmgrKeyDelete(KeyDeleteCommand):
    name = "licmgr key delete"

class _LicmgrKeyRetire(KeyRetireCommand):
    name = "licmgr key retire"

class _LicmgrDbRelinkKeys(DbRelinkKeysCommand):
    name = "licmgr db relink-keys"

class _LicmgrDbExport(DbExportCommand):
    name = "licmgr db export"

class _LicmgrLicenseIssue(LicenseIssueCommand):
    name = "licmgr license issue"

class _LicmgrLicenseList(LicenseListCommand):
    name = "licmgr license list"

class _LicmgrLicenseExport(LicenseExportCommand):
    name = "licmgr license export"

class _LicmgrLicenseRevoke(LicenseRevokeCommand):
    name = "licmgr license revoke"

class _LicmgrLicenseDelete(LicenseDeleteCommand):
    name = "licmgr license delete"

class _LicmgrSdkExport(SdkExportCommand):
    name = "licmgr sdk export"


class _LicmgrTui(Command):
    """Launch the interactive licmgr TUI."""

    name = "licmgr"
    description = "Launch the interactive licmgr TUI (arrow-key menus)"

    def handle(self) -> int:
        """Run the TUI main loop."""
        from licmgr.tui import main
        main()
        return 0


class LicmgrPlugin(ApplicationPlugin):
    """Poetry plugin that registers `poetry licmgr *` commands for license management."""

    def activate(self, application) -> None:  # type: ignore[override]
        """Register all licmgr-namespaced commands with Poetry's command loader."""
        commands = [
            _LicmgrTui,
            _LicmgrProjectCreate,
            _LicmgrProjectList,
            _LicmgrProjectDelete,
            _LicmgrKeyGenerate,
            _LicmgrKeyImport,
            _LicmgrKeyList,
            _LicmgrKeyShow,
            _LicmgrKeyVerify,
            _LicmgrKeyDelete,
            _LicmgrKeyRetire,
            _LicmgrDbRelinkKeys,
            _LicmgrDbExport,
            _LicmgrLicenseIssue,
            _LicmgrLicenseList,
            _LicmgrLicenseExport,
            _LicmgrLicenseRevoke,
            _LicmgrLicenseDelete,
            _LicmgrSdkExport,
        ]
        for cls in commands:
            application.command_loader.register_factory(cls.name, cls)
