"""Database maintenance helpers: key-path relink and selective export.

These functions operate on a SQLAlchemy ``Session`` (so callers control the
transaction and, in tests, can point at a throw-away copy of the DB). They keep
all SQL/file logic out of the TUI so they can be unit tested directly.
"""

import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Base, Key, License, Project


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
