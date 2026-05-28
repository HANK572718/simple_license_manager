"""Database maintenance helpers: key-path relink, selective export, and delete.

These functions operate on a SQLAlchemy ``Session`` (so callers control the
transaction and, in tests, can point at a throw-away copy of the DB). They keep
all SQL/file logic out of the TUI so they can be unit tested directly.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.engine import LICMGR_DATA_DIR
from .db.models import Base, Key, License, Project

# Trash subdirectory under ~/.licmgr/ where deleted artifacts are moved.
# Keeps deletions reversible (operator can mv files back) without polluting the
# working set; ~/.licmgr/ is not in any git repo so this never leaks.
TRASH_DIR_NAME = ".trash"


# ── Scan / relink ───────────────────────────────────────────────────────────


def scan_key_paths(session: Session) -> list[dict]:
    """Return one record per key row describing its private-key path status.

    Args:
        session: Open SQLAlchemy session.

    Returns:
        List of dicts with ``project_id``, ``version``, ``private_key_path``
        and ``exists`` (bool), ordered by project then version.
    """
    rows = session.execute(
        select(Key).order_by(Key.project_id, Key.version)
    ).scalars().all()
    result: list[dict] = []
    for k in rows:
        path = k.private_key_path or ""
        result.append({
            "project_id": k.project_id,
            "version": k.version,
            "private_key_path": path,
            "exists": bool(path) and Path(path).expanduser().is_file(),
        })
    return result


def relink_key(session: Session, project_id: str, version: int, new_path: str) -> bool:
    """Update the ``private_key_path`` of one key row.

    Args:
        session: Open SQLAlchemy session (caller commits).
        project_id: Project the key belongs to.
        version: Key version to update.
        new_path: New filesystem path to store.

    Returns:
        True if a matching key row was found and updated, otherwise False.
    """
    key = session.execute(
        select(Key).where(Key.project_id == project_id, Key.version == version)
    ).scalars().first()
    if key is None:
        return False
    key.private_key_path = new_path
    session.flush()
    return True


def _find_candidate(keys_dir: Path, project_id: str, version: int) -> Path | None:
    """Search *keys_dir* recursively for a private key of the given version.

    Prefers a candidate whose path contains the *project_id* as a directory
    component; otherwise falls back to the first match found.

    Args:
        keys_dir: Root directory to search.
        project_id: Project id used to prefer a better-matching candidate.
        version: Key version embedded in the filename.

    Returns:
        The best candidate path, or None if no file matched.
    """
    target = f"private_key_v{version}.pem"
    matches = [p for p in keys_dir.rglob(target) if p.is_file()]
    if not matches:
        return None
    for p in matches:
        if project_id in p.parts:
            return p
    return matches[0]


def auto_relink(session: Session, keys_dir: Path) -> dict:
    """Try to repair every missing private-key path by searching *keys_dir*.

    For each key whose stored path does not exist, search *keys_dir*
    recursively for ``private_key_v{version}.pem`` (preferring a path under a
    directory matching the project id) and relink it.

    Args:
        session: Open SQLAlchemy session (caller commits).
        keys_dir: Root directory to search for key files.

    Returns:
        Report dict with ``relinked`` (list of dicts: project_id, version,
        old_path, new_path), ``still_missing`` (list of dicts: project_id,
        version, old_path) and ``ok`` (list of project_id/version already
        valid).
    """
    keys_dir = Path(keys_dir).expanduser()
    relinked: list[dict] = []
    still_missing: list[dict] = []
    ok: list[dict] = []

    for entry in scan_key_paths(session):
        if entry["exists"]:
            ok.append({"project_id": entry["project_id"], "version": entry["version"]})
            continue
        candidate = _find_candidate(keys_dir, entry["project_id"], entry["version"])
        if candidate is None:
            still_missing.append({
                "project_id": entry["project_id"],
                "version": entry["version"],
                "old_path": entry["private_key_path"],
            })
            continue
        new_path = str(candidate.resolve())
        relink_key(session, entry["project_id"], entry["version"], new_path)
        relinked.append({
            "project_id": entry["project_id"],
            "version": entry["version"],
            "old_path": entry["private_key_path"],
            "new_path": new_path,
        })

    return {"relinked": relinked, "still_missing": still_missing, "ok": ok}


# ── Selective export ─────────────────────────────────────────────────────────


def export_subset(
    session: Session,
    project_ids: list[str],
    license_ids: list[int],
    out_dir: Path,
) -> dict:
    """Export a portable bundle of selected projects, their keys and licenses.

    Produces, under *out_dir*:
      * ``registry.db`` — a fresh SQLite DB (same schema) containing only the
        selected projects, *all* keys belonging to those projects, and the
        selected licenses.
      * ``keys/<project_id>/`` — copies of every referenced public/private key
        file that exists on disk.

    The exported key rows have their ``private_key_path`` rewritten to a
    *relative* path (``keys/<project_id>/private_key_vN.pem``) so the bundle is
    relocatable.

    Limitations:
        * A license whose ``project_id`` is not in *project_ids* is skipped
          (it would dangle without its project) and reported under
          ``skipped_licenses``.
        * Private-key files that are missing on disk are not copied; the row's
          path is still rewritten to the relative target and the miss is
          reported under ``missing_key_files`` so the operator can supply it.
        * Public keys are stored in the DB as PEM text and are also written out
          as ``public_key_vN.pem`` for convenience.

    Args:
        session: Open SQLAlchemy session to read from.
        project_ids: Project ids to include.
        license_ids: License row ids to include.
        out_dir: Destination directory (created if absent).

    Returns:
        Report dict summarising what was exported / copied / skipped.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _Session

    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    keys_root = out_dir / "keys"

    project_ids = list(project_ids)
    selected_projects = [
        session.get(Project, pid) for pid in project_ids
    ]
    selected_projects = [p for p in selected_projects if p is not None]
    found_pids = {p.id for p in selected_projects}

    # Collect keys for the selected projects.
    keys = session.execute(
        select(Key).where(Key.project_id.in_(found_pids))
    ).scalars().all() if found_pids else []

    # Collect selected licenses, skipping any whose project is not exported.
    skipped_licenses: list[int] = []
    licenses: list[License] = []
    for lid in license_ids:
        lic = session.get(License, lid)
        if lic is None:
            continue
        if lic.project_id not in found_pids:
            skipped_licenses.append(lid)
            continue
        licenses.append(lic)

    # Build the destination DB.
    db_path = out_dir / "registry.db"
    if db_path.exists():
        db_path.unlink()
    dst_engine = create_engine(f"sqlite:///{db_path.as_posix()}", echo=False)
    Base.metadata.create_all(dst_engine)

    copied_keys: list[str] = []
    missing_key_files: list[str] = []

    with _Session(dst_engine, expire_on_commit=False) as dst:
        for p in selected_projects:
            dst.add(Project(
                id=p.id,
                display_name=p.display_name,
                env_prefix=p.env_prefix,
                version=p.version,
                fp_version=p.fp_version,
                validity_days=p.validity_days,
                created_at=p.created_at,
                git_remote=p.git_remote,
                project_root=p.project_root,
                git_user_name=p.git_user_name,
                git_user_email=p.git_user_email,
            ))

        for k in keys:
            proj_keys_dir = keys_root / k.project_id
            proj_keys_dir.mkdir(parents=True, exist_ok=True)

            priv_name = f"private_key_v{k.version}.pem"
            rel_priv = f"keys/{k.project_id}/{priv_name}"

            # Copy the private key file if present on disk.
            src_priv = Path(k.private_key_path).expanduser() if k.private_key_path else None
            if src_priv and src_priv.is_file():
                shutil.copy2(src_priv, proj_keys_dir / priv_name)
                copied_keys.append(rel_priv)
            else:
                missing_key_files.append(
                    f"{k.project_id} v{k.version}: {k.private_key_path}"
                )

            # Write out the public key PEM (always available in DB).
            pub_name = f"public_key_v{k.version}.pem"
            (proj_keys_dir / pub_name).write_text(k.public_key_pem, encoding="utf-8")

            dst.add(Key(
                project_id=k.project_id,
                version=k.version,
                algorithm=k.algorithm,
                public_key_pem=k.public_key_pem,
                public_key_fp=k.public_key_fp,
                private_key_path=rel_priv,
                created_at=k.created_at,
                retired_at=k.retired_at,
                notes=k.notes,
            ))

        for lic in licenses:
            dst.add(License(
                project_id=lic.project_id,
                client_name=lic.client_name,
                machine_fp=lic.machine_fp,
                fp_version=lic.fp_version,
                key_version=lic.key_version,
                mac_hint=lic.mac_hint,
                issued_at=lic.issued_at,
                expires_at=lic.expires_at,
                license_json=lic.license_json,
                lic_file_path=lic.lic_file_path,
                revoked=lic.revoked,
                revoked_at=lic.revoked_at,
                notes=lic.notes,
            ))

        dst.commit()
    dst_engine.dispose()

    missing_projects = [pid for pid in project_ids if pid not in found_pids]
    return {
        "out_dir": str(out_dir.resolve()),
        "db_path": str(db_path.resolve()),
        "projects": sorted(found_pids),
        "missing_projects": missing_projects,
        "keys_exported": len(keys),
        "copied_keys": copied_keys,
        "missing_key_files": missing_key_files,
        "licenses_exported": len(licenses),
        "skipped_licenses": skipped_licenses,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }


# ── Delete: trash + cascading hard delete ────────────────────────────────────


def _trash_root(data_dir: Path | None = None) -> Path:
    """Return the trash root directory (default ``~/.licmgr/.trash/``).

    The optional *data_dir* override is for tests that want an isolated location.
    """
    return Path(data_dir or LICMGR_DATA_DIR) / TRASH_DIR_NAME


def move_to_trash(
    paths: list[Path | str],
    label: str = "delete",
    data_dir: Path | None = None,
) -> tuple[Path | None, list[tuple[Path, Path]]]:
    """Move existing *paths* to a timestamped subdir under the trash root.

    Non-existent paths are silently skipped (treated as already cleaned up). A
    *label* is embedded in the subdir name so the operator can tell what kind of
    delete produced it (e.g. ``20260528-103014-project-DEMO-a1b2``).

    Args:
        paths: Files OR directories to move. Strings are accepted for convenience.
        label: Short tag (e.g. ``project-DEMO``) included in the subdir name.
        data_dir: Optional override for the data dir (tests).

    Returns:
        Tuple of (trash subdir, list of (src, dst) pairs). When nothing existed
        to move, returns ``(None, [])`` — useful so callers can report cleanly.
    """
    existing: list[Path] = []
    for p in paths:
        if not p:
            continue
        path = Path(p).expanduser()
        if path.exists() or path.is_symlink():
            existing.append(path)
    if not existing:
        return None, []

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rand = os.urandom(2).hex()
    trash_dir = _trash_root(data_dir) / f"{ts}-{label}-{rand}"
    trash_dir.mkdir(parents=True, exist_ok=True)

    moved: list[tuple[Path, Path]] = []
    for src in existing:
        # Preserve up to the last 3 path components for human readability.
        rel = Path(*src.parts[-3:]) if len(src.parts) >= 3 else Path(src.name)
        dst = trash_dir / rel
        # If a previous move in this same batch already created the parent, fine.
        dst.parent.mkdir(parents=True, exist_ok=True)
        # If by chance dst already exists (rare in a per-second-timestamped dir),
        # disambiguate to avoid losing data silently.
        if dst.exists():
            dst = dst.with_name(dst.name + f".{os.urandom(2).hex()}")
        shutil.move(str(src), str(dst))
        moved.append((src, dst))
    return trash_dir, moved


def delete_license_with_trash(
    session: Session,
    license_id: int,
    data_dir: Path | None = None,
) -> dict | None:
    """Hard-delete a License row and move its ``.lic`` file to trash.

    Distinct from :func:`crud.revoke_license` which is a soft flag — this is
    permanent removal of the DB record.

    Args:
        session: Open SQLAlchemy session (caller commits).
        license_id: ``License.id`` to delete.
        data_dir: Optional trash-root override for tests.

    Returns:
        Report dict (``license_id`` / ``client`` / ``project_id`` /
        ``trash_dir`` / ``moved_files``) or ``None`` if the license was not found.
    """
    lic = session.get(License, license_id)
    if lic is None:
        return None
    info = {
        "license_id": license_id,
        "client": lic.client_name,
        "project_id": lic.project_id,
    }
    paths: list[Path | str] = []
    if lic.lic_file_path:
        paths.append(lic.lic_file_path)
    trash_dir, moved = move_to_trash(paths, label=f"license-{license_id}", data_dir=data_dir)
    session.delete(lic)
    session.flush()
    info["trash_dir"] = str(trash_dir) if trash_dir else None
    info["moved_files"] = [str(dst) for _, dst in moved]
    return info


def delete_key_with_trash(
    session: Session,
    project_id: str,
    version: int,
    data_dir: Path | None = None,
) -> dict | None:
    """Hard-delete a Key row, cascade-delete its dependent License rows, trash all files.

    Cascade semantics (per design): every License whose ``(project_id, key_version)``
    matches the target key is **hard-deleted** along with the key — including
    already-revoked licenses, because their ``key_version`` reference is about to
    dangle. Their ``.lic`` files (if recorded and present on disk) are moved to
    trash together with the private/public key ``.pem`` files.

    Args:
        session: Open SQLAlchemy session (caller commits).
        project_id: Project the key belongs to.
        version: Key version to delete.
        data_dir: Optional trash-root override for tests.

    Returns:
        Report dict or ``None`` if the key was not found.
    """
    key = session.execute(
        select(Key).where(Key.project_id == project_id, Key.version == version)
    ).scalar_one_or_none()
    if key is None:
        return None

    dep_lics = session.execute(
        select(License).where(
            License.project_id == project_id,
            License.key_version == version,
        )
    ).scalars().all()

    paths: list[Path | str] = []
    if key.private_key_path:
        priv = Path(key.private_key_path).expanduser()
        paths.append(priv)
        # Conventional companion public key — same dir, public_key_vN.pem
        paths.append(priv.parent / f"public_key_v{version}.pem")
    for lic in dep_lics:
        if lic.lic_file_path:
            paths.append(lic.lic_file_path)

    trash_dir, moved = move_to_trash(
        paths, label=f"key-{project_id}-v{version}", data_dir=data_dir
    )

    deleted_license_ids = [lic.id for lic in dep_lics]
    for lic in dep_lics:
        session.delete(lic)
    session.delete(key)
    session.flush()

    return {
        "project_id": project_id,
        "key_version": version,
        "deleted_licenses": deleted_license_ids,
        "trash_dir": str(trash_dir) if trash_dir else None,
        "moved_files": [str(dst) for _, dst in moved],
    }


def delete_project_with_trash(
    session: Session,
    project_id: str,
    data_dir: Path | None = None,
) -> dict | None:
    """Hard-delete a Project; ORM cascade removes its Keys + Licenses; trash all files.

    Files trashed:
      * Every key's ``private_key_path`` + its companion ``public_key_vN.pem``
        (resolved per-key, so custom ``keys_dir`` overrides are honoured).
      * Every license's ``lic_file_path`` (if recorded and present on disk).

    Args:
        session: Open SQLAlchemy session (caller commits).
        project_id: Project id to delete.
        data_dir: Optional trash-root override for tests.

    Returns:
        Report dict or ``None`` if the project was not found.
    """
    project = session.get(Project, project_id)
    if project is None:
        return None
    keys = list(project.keys)
    licenses = list(project.licenses)

    paths: list[Path | str] = []
    seen: set[Path] = set()
    for k in keys:
        if k.private_key_path:
            priv = Path(k.private_key_path).expanduser()
            if priv not in seen:
                paths.append(priv); seen.add(priv)
            pub = priv.parent / f"public_key_v{k.version}.pem"
            if pub not in seen:
                paths.append(pub); seen.add(pub)
    for lic in licenses:
        if lic.lic_file_path:
            p = Path(lic.lic_file_path).expanduser()
            if p not in seen:
                paths.append(p); seen.add(p)

    trash_dir, moved = move_to_trash(
        paths, label=f"project-{project_id}", data_dir=data_dir
    )

    deleted_keys = [(k.version, k.algorithm, k.public_key_fp[:16]) for k in keys]
    deleted_license_ids = [lic.id for lic in licenses]

    # ORM cascade: deleting the Project sweeps its keys + licenses (Project model
    # declares cascade="all, delete-orphan" on both relationships).
    session.delete(project)
    session.flush()

    return {
        "project_id": project_id,
        "deleted_keys": deleted_keys,
        "deleted_licenses": deleted_license_ids,
        "trash_dir": str(trash_dir) if trash_dir else None,
        "moved_files": [str(dst) for _, dst in moved],
    }


def retire_key(session: Session, project_id: str, version: int) -> bool:
    """Soft-retire a key by setting ``retired_at`` to now.

    Reversible: setting ``retired_at`` back to ``None`` re-activates the key.
    Returns ``False`` if the key is not found OR already retired.

    Args:
        session: Open SQLAlchemy session (caller commits).
        project_id: Project the key belongs to.
        version: Key version to retire.
    """
    key = session.execute(
        select(Key).where(Key.project_id == project_id, Key.version == version)
    ).scalar_one_or_none()
    if key is None or key.retired_at is not None:
        return False
    key.retired_at = datetime.now()
    session.flush()
    return True
