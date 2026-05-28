"""CRUD helpers — all SQL access goes through here."""

from datetime import datetime

from sqlalchemy import select

from .engine import get_session
from .models import Key, License, Project


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(
    id: str,
    display_name: str,
    env_prefix: str,
    version: str = "1.0.0",
    fp_version: int = 1,
    validity_days: int = 365,
    git_remote: str | None = None,
    project_root: str | None = None,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
) -> Project:
    """Insert a new Project row and return it."""
    with get_session() as s:
        project = Project(
            id=id,
            display_name=display_name,
            env_prefix=env_prefix,
            version=version,
            fp_version=fp_version,
            validity_days=validity_days,
            created_at=datetime.now(),
            git_remote=git_remote,
            project_root=project_root,
            git_user_name=git_user_name,
            git_user_email=git_user_email,
        )
        s.add(project)
    return project


def list_projects() -> list[Project]:
    """Return all projects."""
    with get_session() as s:
        return s.execute(select(Project).order_by(Project.id)).scalars().all()


def get_project(project_id: str) -> Project | None:
    """Return a Project by id, or None."""
    with get_session() as s:
        return s.get(Project, project_id)


# ── Keys ──────────────────────────────────────────────────────────────────────

def create_key(
    project_id: str,
    version: int,
    public_key_pem: str,
    public_key_fp: str,
    private_key_path: str,
    algorithm: str = "rsa2048",
    notes: str | None = None,
) -> Key:
    """Insert a new Key row and return it."""
    with get_session() as s:
        key = Key(
            project_id=project_id,
            version=version,
            algorithm=algorithm,
            public_key_pem=public_key_pem,
            public_key_fp=public_key_fp,
            private_key_path=private_key_path,
            created_at=datetime.now(),
            notes=notes,
        )
        s.add(key)
    return key


def get_active_key(project_id: str) -> Key | None:
    """Return the newest non-retired key for a project."""
    with get_session() as s:
        return s.execute(
            select(Key)
            .where(Key.project_id == project_id, Key.retired_at.is_(None))
            .order_by(Key.version.desc())
        ).scalars().first()


def list_keys(project_id: str) -> list[Key]:
    """Return all keys for a project, newest first."""
    with get_session() as s:
        return s.execute(
            select(Key).where(Key.project_id == project_id).order_by(Key.version.desc())
        ).scalars().all()


# ── Licenses ──────────────────────────────────────────────────────────────────

def create_license(
    project_id: str,
    client_name: str,
    machine_fp: str,
    key_version: int,
    license_json: str,
    fp_version: int = 1,
    mac_hint: str | None = None,
    expires_at: datetime | None = None,
    lic_file_path: str | None = None,
    notes: str | None = None,
) -> License:
    """Insert a new License row and return it."""
    with get_session() as s:
        lic = License(
            project_id=project_id,
            client_name=client_name,
            machine_fp=machine_fp,
            fp_version=fp_version,
            key_version=key_version,
            mac_hint=mac_hint,
            issued_at=datetime.now(),
            expires_at=expires_at,
            license_json=license_json,
            lic_file_path=lic_file_path,
            notes=notes,
        )
        s.add(lic)
    return lic


def list_licenses(project_id: str) -> list[License]:
    """Return all licenses for a project, newest first."""
    with get_session() as s:
        return s.execute(
            select(License)
            .where(License.project_id == project_id)
            .order_by(License.issued_at.desc())
        ).scalars().all()


def find_licenses_by_fp(
    project_id: str,
    machine_fp: str,
    *,
    only_active: bool = True,
) -> list[License]:
    """Find existing licenses for *machine_fp* under *project_id*.

    Used by the issue-time duplicate-fingerprint guard. Catches cases where
    two licenses end up bound to the same hardware identity — often because a
    vendor-supplied dev machine inherited /etc/machine-id (or similar) from a
    cloned image and the operator unknowingly fingerprinted the same identity
    twice with different client labels.

    Args:
        project_id: Project scope (collisions are per-project).
        machine_fp: 64-hex machine fingerprint to look up.
        only_active: When True (default), exclude already-revoked rows — a
            revoked duplicate is not a real collision (the operator already
            'unlinked' that previous binding).

    Returns:
        Matching License rows, newest first.
    """
    with get_session() as s:
        stmt = select(License).where(
            License.project_id == project_id,
            License.machine_fp == machine_fp,
        )
        if only_active:
            stmt = stmt.where(License.revoked == False)  # noqa: E712 - SQL
        return s.execute(stmt.order_by(License.issued_at.desc())).scalars().all()


def revoke_license(license_id: int) -> bool:
    """Mark a license as revoked. Returns True if found and updated."""
    with get_session() as s:
        lic = s.get(License, license_id)
        if lic is None:
            return False
        lic.revoked = True
        lic.revoked_at = datetime.now()
    return True


def get_license(license_id: int) -> License | None:
    """Return a License by id, or None."""
    with get_session() as s:
        return s.get(License, license_id)


def update_license_file_path(license_id: int, path: str) -> bool:
    """Update lic_file_path for a license record. Returns True if found."""
    with get_session() as s:
        lic = s.get(License, license_id)
        if lic is None:
            return False
        lic.lic_file_path = path
    return True
