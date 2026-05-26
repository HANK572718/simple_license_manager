"""Collect hardware fingerprint and print it for license signing.

This script is safe to distribute to end-users; it contains no secrets.
Supported platforms: Windows, Linux, macOS.

Design rationale
----------------
The core fingerprint is derived ONLY from stable, firmware/OS-level identifiers:

  Layer 1 — OS system ID   : MachineGuid (Win) / machine-id (Linux) / IOPlatformUUID (macOS)
  Layer 2 — BIOS/EFI UUID  : independent of OS image; survives sysprep and reinstalls

MAC address is intentionally excluded from the core fingerprint.
It is collected separately as a human-readable hint stored in the license file,
but does NOT affect the fingerprint value. Reasons:
  - MAC can change from routine operations (NIC replacement, VM rebuild, Wi-Fi randomisation)
  - Free tools (e.g. Technitium TMAC) change it in under 30 seconds — no security value
  - Keeping it out of the hash prevents false license invalidations for legitimate users
"""

import hashlib
import platform
import subprocess
import sys
import uuid
from pathlib import Path

CURRENT_FP_VERSION = 1

# BIOS fields that indicate the OEM never populated the value.
_BIOS_INVALID = frozenset({
    "",
    "to be filled by o.e.m.",
    "default string",
    "not specified",
    "none",
    "n/a",
    "0",
    "00000000-0000-0000-0000-000000000000",
})


# ── Layer 1: OS system ID ─────────────────────────────────────────────────────

def _collect_windows_sysid(parts: list[str]) -> None:
    """Append Windows MachineGuid to *parts*."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        if guid:
            parts.append(f"wguid:{guid}")
    except Exception:
        pass


def _collect_linux_sysid(parts: list[str]) -> None:
    """Append Linux machine-id to *parts*."""
    for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            mid = Path(path).read_text().strip()
            if mid:
                parts.append(f"mid:{mid}")
                return
        except Exception:
            pass


def _collect_macos_sysid(parts: list[str]) -> None:
    """Append macOS IOPlatformUUID to *parts*.

    On Apple Silicon this value is derived from the Secure Enclave UID,
    which is fused into the SoC at manufacturing time and cannot be altered
    by software. On Intel Macs it resides in EFI NVRAM and requires SIP
    to be disabled before it can be modified.
    """
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                uid = line.split('"')[-2]
                if uid:
                    parts.append(f"ioplatform:{uid}")
                return
    except Exception:
        pass


# ── Layer 2: BIOS / EFI UUID ──────────────────────────────────────────────────

def _collect_bios_windows(parts: list[str]) -> None:
    """Append BIOS system UUID via WMI on Windows."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject Win32_ComputerSystemProduct).UUID"],
            capture_output=True, text=True, timeout=10,
        )
        value = result.stdout.strip()
        if value and value.lower() not in _BIOS_INVALID:
            parts.append(f"biosuuid:{value}")
    except Exception:
        pass


def _collect_bios_linux(parts: list[str]) -> None:
    """Append system UUID via dmidecode on Linux (requires root)."""
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-uuid"],
            capture_output=True, text=True, timeout=5,
        )
        value = result.stdout.strip()
        if value and value.lower() not in _BIOS_INVALID:
            parts.append(f"biosuuid:{value}")
    except Exception:
        pass


def _collect_bios_macos(parts: list[str]) -> None:
    """Append Hardware UUID via system_profiler on macOS.

    On Apple Silicon this is derived from the same Secure Enclave source
    as IOPlatformUUID, providing a consistent secondary data point.
    On Intel Macs it comes from EFI NVRAM, independent of the OS image.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "Hardware UUID" in line:
                value = line.split(":")[-1].strip()
                if value and value.lower() not in _BIOS_INVALID:
                    parts.append(f"biosuuid:{value}")
                return
    except Exception:
        pass


# ── MAC hint (not part of fingerprint) ───────────────────────────────────────

def get_mac_hint() -> str | None:
    """Return the MAC address as a human-readable hint, or None if unavailable.

    This value is stored in the license file for auditing purposes only.
    It is NOT included in the fingerprint hash.
    """
    mac = uuid.getnode()
    if mac != 0 and mac != (2**48 - 1):
        return f"{mac:012x}"
    return None


# ── Versioned fingerprint computation ────────────────────────────────────────

def _collect_all_parts() -> list[str]:
    """Collect all available hardware identifier strings."""
    parts: list[str] = []
    system = platform.system()

    if system == "Windows":
        _collect_windows_sysid(parts)
        _collect_bios_windows(parts)
    elif system == "Linux":
        _collect_linux_sysid(parts)
        _collect_bios_linux(parts)
    elif system == "Darwin":
        _collect_macos_sysid(parts)
        _collect_bios_macos(parts)

    return parts


def _compute_v1(parts: list[str]) -> str:
    """v1: SHA-256(sorted([os_system_id, bios_uuid]))."""
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()


def get_fingerprint(version: int = CURRENT_FP_VERSION) -> str:
    """Return a versioned SHA-256 hex fingerprint from stable machine identifiers.

    Args:
        version: Fingerprint algorithm version. Defaults to CURRENT_FP_VERSION.

    Returns:
        64-character lowercase hex string.
    """
    dispatchers = {
        1: _compute_v1,
        # 2: _compute_v2,  # reserved for TPM EK integration
        # 3: _compute_v3,  # reserved for dongle binding
    }
    if version not in dispatchers:
        raise ValueError(f"Unknown fingerprint version: {version}")

    parts = _collect_all_parts()
    if not parts:
        print("ERROR: 無法取得機器識別碼", file=sys.stderr)
        sys.exit(1)

    return dispatchers[version](parts)


if __name__ == "__main__":
    fp = get_fingerprint()
    mac = get_mac_hint()

    print("=" * 60)
    print("請複製以下指紋字串，傳給授權方：")
    print("=" * 60)
    print(fp)
    if mac:
        print(f"\n（參考用 MAC 位址：{mac}，不影響授權驗證）")
    print("=" * 60)
