"""RSA-2048 key pair generation for licmg projects."""

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_key_pair(output_dir: Path, version: int) -> tuple[Path, Path, str, str]:
    """Generate an RSA-2048 key pair and persist to *output_dir*.

    Args:
        output_dir: Directory where the key files will be saved.
        version: Key version number used in the file names.

    Returns:
        Tuple of ``(private_key_path, public_key_path, public_key_pem, public_key_fp)``.
        ``public_key_fp`` is the SHA-256 hex fingerprint of the public key PEM.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    priv_path = output_dir / f"private_key_v{version}.pem"
    pub_path = output_dir / f"public_key_v{version}.pem"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    priv_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    pub_pem_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_path.write_bytes(pub_pem_bytes)

    pub_pem_str = pub_pem_bytes.decode()
    pub_fp = hashlib.sha256(pub_pem_bytes).hexdigest()

    return priv_path, pub_path, pub_pem_str, pub_fp
