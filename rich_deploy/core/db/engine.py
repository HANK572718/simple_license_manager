"""SQLAlchemy engine and session factory for rich_deploy.

Data storage design
-------------------
Private keys and the registry database are stored in ``~/.ssh/rich_deploy/``
so they survive across:
  - git commits / pushes (directory is outside the repo)
  - ``poetry self remove rich-deploy`` (user home is unaffected)
  - Project directory moves or renames

Config resolution order (evaluated at first DB call, not at import):
  1. ``database.url`` in ``rich_deploy.toml`` found in the current working directory
  2. Built-in default: ``~/.ssh/rich_deploy/registry.db``

The ``.ssh`` directory is chosen because it is:
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

_CONFIG_FILENAME = "rich_deploy.toml"

# Global safe data root — survives plugin reinstalls and git operations
RICH_DEPLOY_DATA_DIR: Path = Path.home() / ".ssh" / "rich_deploy"

_engine = None


def _get_default_db_url() -> str:
    """Return the default SQLite URL pointing to the user's safe data directory."""
    db_path = RICH_DEPLOY_DATA_DIR / "registry.db"
    # SQLAlchemy accepts forward slashes on all platforms
    return f"sqlite:///{db_path.as_posix()}"


def _load_db_url() -> str:
    """Read the database URL from rich_deploy.toml in cwd, or return the default."""
    config_path = Path.cwd() / _CONFIG_FILENAME
    if config_path.exists():
        with config_path.open("rb") as f:
            config = tomllib.load(f)
        url = config.get("database", {}).get("url")
        if url:
            return url
    return _get_default_db_url()


def _ensure_data_dir() -> None:
    """Create the data directory with restrictive permissions if it doesn't exist."""
    RICH_DEPLOY_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":  # POSIX only: restrict to owner read/write/execute
        try:
            os.chmod(RICH_DEPLOY_DATA_DIR, stat.S_IRWXU)
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
