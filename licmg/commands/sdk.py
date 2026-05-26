"""Cleo command: sdk export — copy and configure the client SDK for distribution."""

import shutil
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import argument, option

from licmg.core.db.crud import get_active_key, get_project
from licmg.core.db.engine import init_db

# Template files are bundled inside the package at licmg/data/client_sdk/
_TEMPLATE_DIR = Path(__file__).parent.parent / "data" / "client_sdk"

# Placeholder strings in the template verify_license.py (must match exactly)
_PUB_KEY_PLACEHOLDER = 'PUBLIC_KEY_PEM: bytes = b""  # filled in by: tools/main.py → [e] 匯出 SDK'
_ENV_PREFIX_PLACEHOLDER = 'ENV_PREFIX: str = "PROJ"    # filled in by: tools/main.py → [e] 匯出 SDK'


class SdkExportCommand(Command):
    """Export the client SDK for a project, injecting the public key and env prefix."""

    name = "sdk export"
    description = "Export the configured client SDK for a project"

    arguments = [
        argument("project-id", "Project identifier"),
    ]

    options = [
        option(
            "--output", "-o",
            "Output directory (default: ./dist/<project-id>)",
            flag=False,
            default=None,
        ),
        option("--no-guide", None, "Skip copying the integration guide", flag=True),
    ]

    def handle(self) -> int:
        """Execute the command."""
        init_db()

        project_id = self.argument("project-id")
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

        output_raw = self.option("output")
        out_dir = Path(output_raw) if output_raw else Path.cwd() / "dist" / project_id

        if out_dir.exists():
            shutil.rmtree(out_dir)

        if not _TEMPLATE_DIR.exists():
            self.line_error(
                f"<error>Template directory not found: {_TEMPLATE_DIR}\n"
                "Ensure licmg was installed correctly (package data included).</error>"
            )
            return 1

        shutil.copytree(_TEMPLATE_DIR, out_dir)

        # Inject public key and env prefix into verify_license.py
        verify_path = out_dir / "verify_license.py"
        content = verify_path.read_text(encoding="utf-8")

        pub_key_escaped = key.public_key_pem.strip().replace("\\", "\\\\")
        content = content.replace(
            _PUB_KEY_PLACEHOLDER,
            f'PUBLIC_KEY_PEM: bytes = b"""{pub_key_escaped}"""',
        )
        content = content.replace(
            _ENV_PREFIX_PLACEHOLDER,
            f'ENV_PREFIX: str = "{project.env_prefix}"',
        )
        verify_path.write_text(content, encoding="utf-8")

        # Optionally include the integration guide from the repo root
        if not self.option("no-guide"):
            guide_candidates = [
                Path.cwd() / "docs" / "integration_guide.md",
                Path(__file__).parent.parent.parent / "docs" / "integration_guide.md",
            ]
            for guide in guide_candidates:
                if guide.exists():
                    shutil.copy2(guide, out_dir / "integration_guide.md")
                    self.line(f"  Included integration guide from {guide}")
                    break

        self.line(f"<info>SDK exported to {out_dir}</info>")
        self.line(f"  Public key version : v{key.version}")
        self.line(f"  Env prefix         : {project.env_prefix}")
        self.line("")
        self.line("Deliver the output directory to the customer.")
        files = sorted(out_dir.iterdir())
        for f in files:
            self.line(f"  {f.name}")

        return 0
