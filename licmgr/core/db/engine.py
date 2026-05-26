"""SQLAlchemy engine and session factory for licmgr.

Data storage design
-------------------
Private keys and the registry database are stored in ``~/.licmgr/``
so they survive across:
  - git commits / pushes (directory is outside the repo)
  - ``poetry self remove licmgr`` (user home is unaffected)
  - Project directory moves or renames

Config resolution order (evaluated at first DB call, not at import):
  1. ``database.url`` in ``licmgr.toml`` found in the current working directory
  2. Built-in default: ``~/.licmgr/registry.db``

The ``~/.licmgr`` directory is:
  - Protected by OS permissions (chmod 700 on POSIX)
  - Never committed to version control
  - Not cleaned up by package managers
"""

import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine as _create_engine
from sqlalchemy.orm import Session

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .models import Base

_CONFIG_FILENAME = "licmgr.toml"

# Global safe data root — survives plugin reinstalls and git operations
LICMGR_DATA_DIR: Path = Path.home() / ".licmgr"

_engine = None


def _get_default_db_url() -> str:
    """Return the default SQLite URL pointing to the user's safe data directory."""
    db_path = LICMGR_DATA_DIR / "registry.db"
    return f"sqlite:///{db_path.as_posix()}"


def get_config() -> dict:
    """Load and return the full licmgr.toml config dict (or empty dict if none)."""
    config_path = Path.cwd() / _CONFIG_FILENAME
    if config_path.exists():
        with config_path.open("rb") as f:
            return dict(tomllib.load(f))
    return {}


def save_config(config: dict) -> None:
    """Write the given config dict to licmgr.toml in the current working directory."""
    lines: list[str] = []

    db_section = config.get("database", {})
    if db_section:
        lines.append("[database]")
        for k, v in db_section.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")

    storage_section = config.get("storage", {})
    if storage_section:
        lines.append("[storage]")
        for k, v in storage_section.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")

    defaults_section = config.get("defaults", {})
    if defaults_section:
        lines.append("[defaults]")
        for k, v in defaults_section.items():
            if isinstance(v, (int, float, bool)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{v}"')
        lines.append("")

    config_path = Path.cwd() / _CONFIG_FILENAME
    config_path.write_text("\n".join(lines), encoding="utf-8")


def _load_db_url() -> str:
    """Read the database URL from licmgr.toml in cwd, or return the default."""
    url = get_config().get("database", {}).get("url")
    return url if url else _get_default_db_url()


def _ensure_data_dir() -> None:
    """Create the data directory with restrictive permissions if it doesn't exist."""
    LICMGR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":  # POSIX only: restrict to owner read/write/execute
        try:
            os.chmod(LICMGR_DATA_DIR, stat.S_IRWXU)
        except OSError:
            pass


def get_engine():
    """Return the shared SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        url = _load_db_url()
        _engine = _create_engine(url, echo=False)
    return _engine


def init_db() -> None:
    """Create the data directory and all DB tables if they do not exist."""
    _ensure_data_dir()
    Base.metadata.create_all(get_engine())


@contextmanager
def get_session():
    """Yield a SQLAlchemy Session and commit/rollback automatically."""
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
