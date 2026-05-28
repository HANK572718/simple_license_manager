"""Public/private RSA key-pair matching checks.

This module verifies that a given RSA private key corresponds to a public key
that may come from several sources used in the licmgr workflow:

  * a public-key PEM (file or pasted text),
  * the ``PUBLIC_KEY_PEM`` literal embedded in an integration's
    ``verify_license.py``,
  * a signed ``.lic`` file (functional check: did this private key sign it?).

All functions here are pure and import-safe so they can be unit tested without
a database, a TUI, or any global state.
"""

import base64
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
)


def derive_public_pem(private_pem: bytes) -> bytes:
    """Return the public-key PEM derived from an RSA private-key PEM.

    Args:
        private_pem: PEM-encoded RSA private key bytes.

    Returns:
        SubjectPublicKeyInfo PEM bytes of the matching public key.
    """
    private_key = load_pem_private_key(private_pem, password=None)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def keys_match(private_pem: bytes, public_pem: bytes) -> bool:
    """Return True if *public_pem* is the public key of *private_pem*.

    The comparison is on the RSA public numbers (modulus ``n`` and public
    exponent ``e``) so it is robust to PEM formatting differences.

    Args:
        private_pem: PEM-encoded RSA private key bytes.
        public_pem: PEM-encoded RSA public key bytes.

    Returns:
        True if the two keys form a pair, otherwise False.
    """
    priv_pub = load_pem_private_key(private_pem, password=None).public_key()
    pub = load_pem_public_key(public_pem)
    a = priv_pub.public_numbers()
    b = pub.public_numbers()
    return a.n == b.n and a.e == b.e


def parse_pubkey_from_verify_license(text: str) -> bytes:
    """Extract the ``PUBLIC_KEY_PEM`` literal from a ``verify_license.py`` source.

    Handles both the triple-quoted bytes literal::

        PUBLIC_KEY_PEM: bytes = b\"\"\"-----BEGIN PUBLIC KEY-----
        ...
        -----END PUBLIC KEY-----\"\"\"

    and a single/double-quoted single-line ``b"..."`` literal.

    Args:
        text: Full source text of a ``verify_license.py`` file.

    Returns:
        The PEM bytes of the embedded public key.

    Raises:
        ValueError: If no non-empty ``PUBLIC_KEY_PEM`` literal can be found.
    """
    # Triple-quoted form: b""" ... """ or b''' ... '''
    triple = re.search(
        r"PUBLIC_KEY_PEM[^=]*=\s*b(?P<q>\"\"\"|''')(?P<body>.*?)(?P=q)",
        text,
        re.DOTALL,
    )
    if triple:
        body = triple.group("body")
        if body.strip():
            return body.encode()

    # Single-line form: b"..." or b'...'
    single = re.search(
        r"PUBLIC_KEY_PEM[^=]*=\s*b(?P<q>[\"'])(?P<body>.*?)(?P=q)",
        text,
        re.DOTALL,
    )
    if single:
        body = single.group("body")
        if body.strip():
            # Decode escape sequences such as \n that may appear in a
            # single-line bytes literal.
            return body.encode().decode("unicode_escape").encode()

    raise ValueError("No non-empty PUBLIC_KEY_PEM literal found in source text.")


def lic_signature_matches(private_pem: bytes, lic: dict) -> bool:
    """Return True if *private_pem* is the key that signed the *lic* dict.

    Rebuilds the signed payload from the ``.lic`` fields using the same format
    as :func:`licmgr.core.sign_license.sign` and verifies the base64
    ``signature`` against the public key derived from *private_pem*.

    Args:
        private_pem: PEM-encoded RSA private key bytes.
        lic: Parsed ``.lic`` JSON dict with ``fingerprint``, ``fp_version``,
            ``signature`` and optional ``expires``.

    Returns:
        True if the signature verifies under this private key's public key,
        otherwise False.
    """
    try:
        fingerprint = lic["fingerprint"]
        fp_version = lic["fp_version"]
        signature = base64.b64decode(lic["signature"])
    except (KeyError, TypeError, ValueError):
        return False

    payload = f"{fingerprint}|fp_version:{fp_version}"
    expires = lic.get("expires")
    if expires:
        payload += f"|expires:{expires}"

    public_key = load_pem_private_key(private_pem, password=None).public_key()
    try:
        public_key.verify(signature, payload.encode(), PKCS1v15(), SHA256())
        return True
    except Exception:
        return False


def verify_keypair(
    private_pem: bytes,
    *,
    public_pem: bytes | None = None,
    lic: dict | None = None,
) -> tuple[bool, str]:
    """Dispatch a key-pair check against a public key or a signed license.

    Exactly one of *public_pem* or *lic* must be supplied.

    Args:
        private_pem: PEM-encoded RSA private key bytes.
        public_pem: Optional public-key PEM to compare against.
        lic: Optional parsed ``.lic`` dict to functionally verify against.

    Returns:
        Tuple ``(matched, reason)`` where *matched* is the boolean result and
        *reason* is a one-line human-readable explanation.
    """
    if (public_pem is None) == (lic is None):
        return False, "需提供 public_pem 或 lic 其中一個（且只能一個）。"

    try:
        if public_pem is not None:
            matched = keys_match(private_pem, public_pem)
            if matched:
                return True, "私鑰與公鑰為同一組金鑰對（modulus/exponent 相符）。"
            return False, "公鑰與此私鑰不相符（modulus/exponent 不同）。"

        matched = lic_signature_matches(private_pem, lic)
        if matched:
            return True, "此 .lic 的簽章可用此私鑰的公鑰驗證通過。"
        return False, "此 .lic 的簽章無法用此私鑰驗證（並非此金鑰簽發）。"
    except Exception as exc:  # noqa: BLE001 - surface load/parse errors as reason
        return False, f"驗證時發生錯誤：{exc}"
