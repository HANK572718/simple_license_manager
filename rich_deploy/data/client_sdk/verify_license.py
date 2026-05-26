"""Verify a license file against this machine's hardware fingerprint.

Deploy-time configuration
--------------------------
Replace the two constants below before distributing to a customer:

  PUBLIC_KEY_PEM  — paste the PEM content from tools/public_key.pem
  ENV_PREFIX      — the project environment-variable prefix (e.g. "NHAD")

The license file path is read from:
  1. Environment variable  <ENV_PREFIX>_LICENSE_FILE
  2. Default path          ./license.lic
"""

import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

# ── Deploy-time constants (replace per project) ───────────────────────────────

PUBLIC_KEY_PEM: bytes = b""  # filled in by: tools/main.py → [e] 匯出 SDK
ENV_PREFIX: str = "PROJ"    # filled in by: tools/main.py → [e] 匯出 SDK

# ─────────────────────────────────────────────────────────────────────────────

# Lazy import so this file can be imported without cryptography installed
# during bootstrap detection.
def _load_public_key(pem: bytes):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    return load_pem_public_key(pem)


def _resolve_license_path(override: str | None = None) -> Path:
    """Return the license file path from argument, env var, or default."""
    if override:
        return Path(override)
    env_key = f"{ENV_PREFIX}_LICENSE_FILE"
    env_val = os.environ.get(env_key)
    if env_val:
        return Path(env_val)
    return Path("license.lic")


def verify_license(
    license_path: str | Path | None = None,
    public_key_pem: bytes = PUBLIC_KEY_PEM,
) -> bool:
    """Verify the license against this machine's fingerprint.

    Three gates are checked in order:
      1. Fingerprint match  — license was issued for this machine
      2. Expiry date        — license is still valid today
      3. RSA signature      — license was not tampered with

    Returns:
        True if all gates pass, False otherwise. Never raises.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
        from cryptography.hazmat.primitives.hashes import SHA256

        from .get_fingerprint import CURRENT_FP_VERSION, get_fingerprint
    except ImportError:
        # Allow running as a standalone script (no package context)
        import importlib.util, pathlib
        _here = pathlib.Path(__file__).parent
        spec = importlib.util.spec_from_file_location(
            "get_fingerprint", _here / "get_fingerprint.py"
        )
        _gf = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(_gf)  # type: ignore[union-attr]
        get_fingerprint = _gf.get_fingerprint
        CURRENT_FP_VERSION = _gf.CURRENT_FP_VERSION

        from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
        from cryptography.hazmat.primitives.hashes import SHA256

    try:
        path = _resolve_license_path(str(license_path) if license_path else None)
        if not path.exists():
            print(f"[verify] 找不到授權檔：{path}", file=sys.stderr)
            return False

        lic = json.loads(path.read_text(encoding="utf-8"))

        # ── Gate 1: fingerprint match ─────────────────────────────────────────
        fp_version: int = lic.get("fp_version", CURRENT_FP_VERSION)
        machine_fp = get_fingerprint(version=fp_version)
        if machine_fp != lic.get("fingerprint"):
            print("[verify] ✗ 關卡一：指紋不符，此授權不屬於本機", file=sys.stderr)
            return False

        # ── Gate 2: expiry ────────────────────────────────────────────────────
        expires_str: str | None = lic.get("expires")
        if expires_str:
            expires_date = date.fromisoformat(expires_str)
            if date.today() > expires_date:
                print(f"[verify] ✗ 關卡二：授權已於 {expires_str} 到期", file=sys.stderr)
                return False

        # ── Gate 3: RSA signature ─────────────────────────────────────────────
        if not public_key_pem:
            print("[verify] ✗ 關卡三：未設定公鑰，無法驗簽", file=sys.stderr)
            return False

        pub_key = _load_public_key(public_key_pem)
        payload = f"{lic['fingerprint']}|fp_version:{fp_version}"
        if expires_str:
            payload += f"|expires:{expires_str}"

        sig = base64.b64decode(lic["signature"])
        pub_key.verify(sig, payload.encode(), PKCS1v15(), SHA256())

        return True

    except Exception as exc:
        print(f"[verify] ✗ 關卡三：簽章驗證失敗 — {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify a license file.")
    parser.add_argument("license", nargs="?", help="Path to license.lic")
    parser.add_argument("--pubkey", help="Path to public key PEM file")
    args = parser.parse_args()

    pem = PUBLIC_KEY_PEM
    if args.pubkey:
        pem = Path(args.pubkey).read_bytes()

    ok = verify_license(license_path=args.license, public_key_pem=pem)
    if ok:
        print("✓ 授權驗證通過")
        sys.exit(0)
    else:
        print("✗ 授權驗證失敗")
        sys.exit(1)
