"""Import an existing RSA private key and (re)build its registry rows.

This is the inverse of :func:`licmgr.core.generate_keys.generate_key_pair`:
instead of creating a fresh key pair, it takes a private key that already
exists on disk, derives the matching public key and fingerprint, and writes /
repairs the ``keys`` (and if needed ``projects``) DB rows.

The derived public key is **byte-identical** to what ``generate_keys`` would
have produced for the same private key, so any public key / ``.lic`` file that
was previously shipped for this key pair stays valid (no re-signing needed).

Like :mod:`licmgr.core.dbmaint`, every function takes a SQLAlchemy ``Session``
so callers control the transaction and tests can point at a throw-away copy of
the registry. All SQL/file logic lives here; the TUI and CLI stay thin.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import Key, Project


def derive_public_material(private_pem: bytes) -> tuple[str, str]:
    """Derive the public-key PEM and its SHA-256 fingerprint from a private key.

    Replicates :func:`licmgr.core.generate_keys.generate_key_pair` exactly so
    the result is byte-identical to a previously-shipped public key.

    Args:
        private_pem: PEM-encoded RSA private key bytes (unencrypted).

    Returns:
        Tuple of ``(public_key_pem, public_key_fp)`` where the PEM is the
        decoded SubjectPublicKeyInfo string and the fingerprint is the
        hex SHA-256 of the PEM bytes.

    Raises:
        ValueError: If the PEM cannot be loaded or is not an RSA private key.
    """
    try:
        private_key = serialization.load_pem_private_key(private_pem, password=None)
    except Exception as exc:  # noqa: BLE001 - surface load errors as ValueError
        raise ValueError(f"無法載入私鑰 PEM：{exc}") from exc

    if not isinstance(private_key, RSAPrivateKey):
        raise ValueError("提供的私鑰不是 RSA 金鑰，licmgr 僅支援 RSA。")

    pub_pem_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_fp = hashlib.sha256(pub_pem_bytes).hexdigest()
    return pub_pem_bytes.decode(), public_key_fp


def import_private_key(
    session: Session,
    project_id: str,
    private_key_path: str | Path,
    *,
    version: int = 1,
    env_prefix: str | None = None,
    create_project: bool = True,
    write_public_pem: bool = True,
    validity_days: int = 365,
) -> dict:
    """Import an existing private key into the registry, deriving its public key.

    Idempotent / repair semantics:
      * If the ``(project_id, version)`` key row already exists, its
        ``public_key_pem`` / ``public_key_fp`` / ``private_key_path`` are
        updated (action ``"updated"``).
      * If the project exists but the key version does not, the key row is
        added (action ``"created"``).
      * If the project is missing and *create_project* is True, the project is
        created first with sensible defaults (display_name = project_id,
        version "1.0.0", fp_version 1, validity_days, env_prefix per the rule
        below). Git provenance fields are intentionally left None.

    The ``env_prefix`` is never left None — it drives the client's
    ``<PREFIX>_LICENSE_FILE`` lookup. When creating a new project it defaults to
    *project_id* if not supplied.

    No ``licenses`` rows are fabricated: issued-license history cannot be
    reconstructed from a private key, so the ``licenses`` table is untouched.

    Args:
        session: Open SQLAlchemy session (caller commits).
        project_id: Project the key belongs to.
        private_key_path: Path to the existing ``.pem`` private key file.
        version: Key version number (matches the ``private_key_vN.pem`` scheme).
        env_prefix: Env-var prefix; defaults to *project_id* when creating a
            new project. Ignored when the project already exists.
        create_project: Create the project if it is missing (else raise).
        write_public_pem: Also write a ``public_key_v{version}.pem`` next to the
            private key for convenience.
        validity_days: Default license validity for a newly-created project.

    Returns:
        Summary dict with keys ``project_created`` (bool),
        ``key_action`` (``"created"`` | ``"updated"``), ``public_key_fp`` (str),
        ``public_key_path`` (str | None, the on-disk PEM if written), and
        ``env_prefix`` (str, the value stored for the project).

    Raises:
        ValueError: If the private key file is missing, cannot be loaded, is
            not RSA, or the project is missing and *create_project* is False.
    """
    priv_path = Path(private_key_path).expanduser()
    if not priv_path.is_file():
        raise ValueError(f"找不到私鑰檔案：{priv_path}")

    resolved_priv = str(priv_path.resolve())
    public_key_pem, public_key_fp = derive_public_material(priv_path.read_bytes())

    # ── Project row ────────────────────────────────────────────────────────
    project = session.get(Project, project_id)
    project_created = False
    if project is None:
        if not create_project:
            raise ValueError(
                f"專案 '{project_id}' 不存在，且未允許建立（create_project=False）。"
            )
        resolved_prefix = (env_prefix or project_id)
        project = Project(
            id=project_id,
            display_name=project_id,
            env_prefix=resolved_prefix,
            version="1.0.0",
            fp_version=1,
            validity_days=validity_days,
            created_at=datetime.now(),
            # Non-derivable provenance: left None on purpose.
            git_remote=None,
            project_root=None,
            git_user_name=None,
            git_user_email=None,
        )
        session.add(project)
        session.flush()
        project_created = True

    stored_prefix = project.env_prefix

    # ── Key row (create or repair) ─────────────────────────────────────────
    key = session.execute(
        select(Key).where(Key.project_id == project_id, Key.version == version)
    ).scalars().first()
    if key is None:
        key = Key(
            project_id=project_id,
            version=version,
            algorithm="rsa2048",
            public_key_pem=public_key_pem,
            public_key_fp=public_key_fp,
            private_key_path=resolved_priv,
            created_at=datetime.now(),
            notes="imported from existing private key",
        )
        session.add(key)
        key_action = "created"
    else:
        key.public_key_pem = public_key_pem
        key.public_key_fp = public_key_fp
        key.private_key_path = resolved_priv
        key_action = "updated"
    session.flush()

    # ── Optional convenience public PEM next to the private key ────────────
    public_key_path: str | None = None
    if write_public_pem:
        pub_path = priv_path.parent / f"public_key_v{version}.pem"
        pub_path.write_text(public_key_pem, encoding="utf-8")
        public_key_path = str(pub_path.resolve())

    return {
        "project_created": project_created,
        "key_action": key_action,
        "public_key_fp": public_key_fp,
        "public_key_path": public_key_path,
        "env_prefix": stored_prefix,
    }
