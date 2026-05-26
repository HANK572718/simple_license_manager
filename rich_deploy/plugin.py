"""Poetry ApplicationPlugin entry point for rich_deploy.

Installation:
    poetry self add rich-deploy

Usage (from the rich_deploy project directory):
    poetry rd project create MY_PROJ "My Project" MYPROJ
    poetry rd project list
    poetry rd key generate MY_PROJ
    poetry rd key list MY_PROJ
    poetry rd license issue MY_PROJ <fingerprint> --client "Acme Corp" --expires 2027-12-31
    poetry rd license list MY_PROJ
    poetry rd license export <id> --output /path/to/license.lic
    poetry rd license revoke <id>
    poetry rd sdk export MY_PROJ --output /path/to/dist
"""

from poetry.plugins.application_plugin import ApplicationPlugin

from rich_deploy.commands.key import KeyGenerateCommand, KeyListCommand, KeyShowCommand
from rich_deploy.commands.license import (
    LicenseExportCommand,
    LicenseIssueCommand,
    LicenseListCommand,
    LicenseRevokeCommand,
)
from rich_deploy.commands.project import ProjectCreateCommand, ProjectListCommand
from rich_deploy.commands.sdk import SdkExportCommand


# Thin wrappers that add the "rd " namespace prefix for Poetry plugin commands.
# The base command classes keep their short names for the standalone CLI.

class _RdProjectCreate(ProjectCreateCommand):
    name = "rd project create"

class _RdProjectList(ProjectListCommand):
    name = "rd project list"

class _RdKeyGenerate(KeyGenerateCommand):
    name = "rd key generate"

class _RdKeyList(KeyListCommand):
    name = "rd key list"

class _RdKeyShow(KeyShowCommand):
    name = "rd key show"

class _RdLicenseIssue(LicenseIssueCommand):
    name = "rd license issue"

class _RdLicenseList(LicenseListCommand):
    name = "rd license list"

class _RdLicenseExport(LicenseExportCommand):
    name = "rd license export"

class _RdLicenseRevoke(LicenseRevokeCommand):
    name = "rd license revoke"

class _RdSdkExport(SdkExportCommand):
    name = "rd sdk export"


class RichDeployPlugin(ApplicationPlugin):
    """Poetry plugin that registers `poetry rd *` commands for license management."""

    def activate(self, application) -> None:  # type: ignore[override]
        """Register all rd-namespaced commands with Poetry's command loader."""
        commands = [
            _RdProjectCreate,
            _RdProjectList,
            _RdKeyGenerate,
            _RdKeyList,
            _RdKeyShow,
            _RdLicenseIssue,
            _RdLicenseList,
            _RdLicenseExport,
            _RdLicenseRevoke,
            _RdSdkExport,
        ]
        for cls in commands:
            application.command_loader.register_factory(cls.name, cls)
