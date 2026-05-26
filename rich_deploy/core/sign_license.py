"""Sign a machine fingerprint with the project's RSA private key.

This module must only run on the developer's machine where the private key is held.
The ``private_key_path`` parameter lets callers pass the project-specific key
instead of relying on a module-level default, avoiding the need for path patching.
"""

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import load_pem_private_key

_FP_LEN = 64
_HEX_CHARS = frozenset("0123456789abcdef")


def _load_private_key(path: Path):
    """Load and return the RSA private key from *path*."""
    if not path.exists():
        print(f"ERROR: private key not found: {path}", file=sys.stderr)
        sys.exit(1)
    return load_pem_private_key(path.read_bytes(), password=None)


def _validate_fingerprint(fp: str) -> str:
    """Return *fp* unchanged, or raise ValueError if the format is invalid."""
    if len(fp) != _FP_LEN or not all(c in _HEX_CHARS for c in fp):
        raise ValueError(
            f"Invalid fingerprint: expected {_FP_LEN} lowercase hex chars, got {fp!r}"
        )
    return fp


def sign(
    fingerprint: str,
    expires: str | None = None,
    mac_hint: str | None = None,
    note: str | None = None,
    fp_version: int = 1,
    private_key_path: Path | None = None,
) -> dict:
    """Sign *fingerprint* and return the license dict ready for serialisation.

    Args:
        fingerprint: 64-char hex SHA-256 machine fingerprint.
        expires: Optional ISO-8601 expiry date string (``YYYY-MM-DD``).
        mac_hint: MAC address for audit record only — not included in the
            signed payload and does not affect license validation.
        note: Human-readable note embedded in the license (e.g. customer name).
        fp_version: Fingerprint algorithm version; included in the signed
            payload to prevent downgrade attacks.
        private_key_path: Path to the PEM private key file.  When *None*,
            falls back to a ``private_key.pem`` sibling of this module.

    Returns:
        License dict with ``fingerprint``, ``fp_version``, ``signature``, and
        optional ``expires`` / ``mac_hint`` fields.
    """
    fingerprint = _validate_fingerprint(fingerprint.strip())

    if private_key_path is None:
        private_key_path = Path(__file__).parent / "private_key.pem"

    private_key = _load_private_key(private_key_path)

    # Signed payload includes fp_version to prevent downgrade attacks.
    # MAC is intentionally excluded so hardware changes don't break licenses.
    payload = f"{fingerprint}|fp_version:{fp_version}"
    if expires:
        payload += f"|expires:{expires}"

    signature = private_key.sign(payload.encode(), PKCS1v15(), SHA256())
    sig_b64 = base64.b64encode(signature).decode()

    license_data: dict = {
        "fingerprint": fingerprint,
        "fp_version": fp_version,
        "signature": sig_b64,
        "note": note or "",
    }
    if expires:
        license_data["expires"] = expires
    if mac_hint:
        license_data["mac_hint"] = mac_hint

    return license_data
