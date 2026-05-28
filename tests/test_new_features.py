"""Tests for the new keycheck and dbmaint core modules.

Run with the repo's own environment, e.g.::

    cd /home/suser/simple_license_manager && poetry run python tests/test_new_features.py

The real registry DB is never mutated — it is copied to a temp file first.
"""

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Allow running as a plain script (PYTHONPATH=repo root) or via pytest.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from licmgr.core import keycheck
from licmgr.core import dbmaint
from licmgr.core import import_key
from licmgr.core.db.models import Key, License, Project


# ── Fixtures / test data ──────────────────────────────────────────────────────

ORIGIN_PRIV = Path("/home/suser/.licmgr/projects/origin_ssopg_key/private_key_v1.pem")
SSOPG_PUB = Path("/home/suser/.licmgr/projects/SSOPG/keys/public_key_v1.pem")
VERIFY_LICENSE = Path("/home/suser/nh-smartsop/license/GIT_SmartSOPGuardian/verify_license.py")
LIC_FILE = Path("/tmp/relink_test.lic")
REGISTRY_DB = Path("/home/suser/.licmgr/registry.db")

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    """Record and print a single assertion result."""
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


# ── keycheck tests ─────────────────────────────────────────────────────────────

def test_keycheck() -> None:
    """Cover derive/match/parse/lic-signature against real key material."""
    print("[keycheck]")
    priv = ORIGIN_PRIV.read_bytes()

    # parse_pubkey_from_verify_license returns valid PEM
    pub_from_vl = keycheck.parse_pubkey_from_verify_license(VERIFY_LICENSE.read_text())
    check(
        "parse_pubkey_from_verify_license returns PEM",
        pub_from_vl.startswith(b"-----BEGIN PUBLIC KEY-----"),
        repr(pub_from_vl[:40]),
    )

    # origin private key vs verify_license.py embedded public key -> MATCH
    check(
        "origin priv vs verify_license pub -> MATCH",
        keycheck.keys_match(priv, pub_from_vl),
    )

    # derive_public_pem agrees with the embedded public key
    derived = keycheck.derive_public_pem(priv)
    check(
        "derive_public_pem matches embedded pub",
        keycheck.keys_match(priv, derived),
    )

    # origin private key vs /tmp/relink_test.lic -> MATCH (functional)
    lic = json.loads(LIC_FILE.read_text())
    check(
        "origin priv vs relink_test.lic signature -> MATCH",
        keycheck.lic_signature_matches(priv, lic),
    )

    # origin private key vs SSOPG public key -> NO MATCH
    ssopg_pub = SSOPG_PUB.read_bytes()
    check(
        "origin priv vs SSOPG pub -> NO MATCH",
        not keycheck.keys_match(priv, ssopg_pub),
    )

    # dispatcher: public_pem path
    ok, reason = keycheck.verify_keypair(priv, public_pem=pub_from_vl)
    check("verify_keypair(public_pem) MATCH", ok, reason)
    ok2, _ = keycheck.verify_keypair(priv, public_pem=ssopg_pub)
    check("verify_keypair(public_pem) NO MATCH for SSOPG", not ok2)

    # dispatcher: lic path
    ok3, reason3 = keycheck.verify_keypair(priv, lic=lic)
    check("verify_keypair(lic) MATCH", ok3, reason3)

    # dispatcher: bad args
    ok4, _ = keycheck.verify_keypair(priv)
    check("verify_keypair with no target -> False", not ok4)


# ── dbmaint tests ──────────────────────────────────────────────────────────────

def test_dbmaint() -> None:
    """Cover scan/relink/auto_relink/export on a COPY of the registry DB."""
    print("[dbmaint]")
    tmp = Path(tempfile.mkdtemp(prefix="licmgr_test_"))
    db_copy = tmp / "registry.db"
    shutil.copy2(REGISTRY_DB, db_copy)
    engine = create_engine(f"sqlite:///{db_copy.as_posix()}", echo=False)

    with Session(engine, expire_on_commit=False) as s:
        rows = dbmaint.scan_key_paths(s)
        check("scan_key_paths returns rows", len(rows) > 0, str(len(rows)))
        check(
            "scan_key_paths has exists flag",
            all("exists" in r and "private_key_path" in r for r in rows),
        )
        # GIT_SmartSOPGuardian key should exist (relinked & valid)
        git_row = next(
            (r for r in rows if r["project_id"] == "GIT_SmartSOPGuardian"), None
        )
        check("GIT_SmartSOPGuardian key row present", git_row is not None)
        if git_row:
            check("GIT_SmartSOPGuardian path exists", git_row["exists"], git_row["private_key_path"])

        # relink_key changes a path
        changed = dbmaint.relink_key(s, "GIT_SmartSOPGuardian", 1, "/tmp/nonexistent_xyz.pem")
        s.commit()
        check("relink_key returns True", changed)
        new_rows = dbmaint.scan_key_paths(s)
        git_now = next(r for r in new_rows if r["project_id"] == "GIT_SmartSOPGuardian")
        check(
            "relink_key actually updated path",
            git_now["private_key_path"] == "/tmp/nonexistent_xyz.pem",
            git_now["private_key_path"],
        )
        check("relinked path now missing", not git_now["exists"])

        # auto_relink finds the key under a keys_dir
        keys_dir = Path("/home/suser/.licmgr/projects")
        report = dbmaint.auto_relink(s, keys_dir)
        s.commit()
        relinked_git = any(
            r["project_id"] == "GIT_SmartSOPGuardian" for r in report["relinked"]
        )
        check("auto_relink relinked GIT_SmartSOPGuardian", relinked_git, str(report["relinked"]))
        after = dbmaint.scan_key_paths(s)
        git_after = next(r for r in after if r["project_id"] == "GIT_SmartSOPGuardian")
        check("auto_relink restored a valid path", git_after["exists"], git_after["private_key_path"])

        # relink_key returns False for unknown key
        check("relink_key unknown -> False", not dbmaint.relink_key(s, "NOPE", 9, "/x"))

        # export_subset writes a portable bundle
        out_dir = tmp / "bundle"
        exp = dbmaint.export_subset(s, ["GIT_SmartSOPGuardian"], [], out_dir)
        check("export created registry.db", (out_dir / "registry.db").is_file())
        check("export_subset reports project", "GIT_SmartSOPGuardian" in exp["projects"])
        # exported DB has relative key path
        exp_engine = create_engine(f"sqlite:///{(out_dir / 'registry.db').as_posix()}")
        with Session(exp_engine) as es:
            ek = es.query(Key).filter_by(project_id="GIT_SmartSOPGuardian").first()
            check(
                "exported key path is relative",
                ek is not None and ek.private_key_path.startswith("keys/GIT_SmartSOPGuardian/"),
                ek.private_key_path if ek else "no key",
            )
            check(
                "exported private key file copied",
                (out_dir / ek.private_key_path).is_file() if ek else False,
            )
        exp_engine.dispose()

    engine.dispose()
    shutil.rmtree(tmp, ignore_errors=True)


# ── import_key tests ─────────────────────────────────────────────────────────

def test_import_key() -> None:
    """Import the origin private key as a NEW project on a COPY of the DB.

    The origin private key is GIT_SmartSOPGuardian's key, so the derived public
    key / fingerprint must equal what is already stored for that project, while
    the import targets a fresh project id and creates no license rows.
    """
    print("[import_key]")
    real_sha_before = hashlib.sha256(REGISTRY_DB.read_bytes()).hexdigest()

    tmp = Path(tempfile.mkdtemp(prefix="licmgr_import_test_"))
    db_copy = tmp / "registry.db"
    shutil.copy2(REGISTRY_DB, db_copy)
    engine = create_engine(f"sqlite:///{db_copy.as_posix()}", echo=False)

    # Copy the private key into the temp dir so we don't write a public PEM
    # next to the real key material.
    priv_copy = tmp / "private_key_v1.pem"
    shutil.copy2(ORIGIN_PRIV, priv_copy)

    with Session(engine, expire_on_commit=False) as s:
        # Read what GIT_SmartSOPGuardian already stores (the "original" pub key).
        git_key = s.query(Key).filter_by(project_id="GIT_SmartSOPGuardian").first()
        check("GIT_SmartSOPGuardian key present in copy", git_key is not None)
        stored_pem = git_key.public_key_pem
        stored_fp = git_key.public_key_fp

        summary = import_key.import_private_key(
            s, "IMPORT_TEST", priv_copy, version=1,
        )
        s.commit()

        check("project_created is True", summary["project_created"] is True)
        check("key_action is created", summary["key_action"] == "created", summary["key_action"])

        new_key = s.query(Key).filter_by(project_id="IMPORT_TEST").first()
        check("IMPORT_TEST key row created", new_key is not None)

        # Core correctness: derived pub == stored GIT pub (byte-identical).
        check(
            "derived public_key_pem == stored GIT pem",
            new_key is not None and new_key.public_key_pem == stored_pem,
        )
        check(
            "derived public_key_fp == stored GIT fp",
            new_key is not None and new_key.public_key_fp == stored_fp,
            f"{new_key.public_key_fp if new_key else '?'} vs {stored_fp}",
        )

        # private_key_path is the absolute resolved path of the given .pem.
        check(
            "key private_key_path is absolute resolved path",
            new_key is not None and new_key.private_key_path == str(priv_copy.resolve()),
            new_key.private_key_path if new_key else "no key",
        )

        # projects row: env_prefix defaulted to id, git_* None.
        proj = s.get(Project, "IMPORT_TEST")
        check("IMPORT_TEST project row exists", proj is not None)
        check(
            "env_prefix defaulted to project id",
            proj is not None and proj.env_prefix == "IMPORT_TEST",
            proj.env_prefix if proj else "no project",
        )
        check(
            "git_* fields left None",
            proj is not None and proj.git_remote is None and proj.project_root is None
            and proj.git_user_name is None and proj.git_user_email is None,
        )
        check("env_prefix in summary", summary["env_prefix"] == "IMPORT_TEST")

        # No licenses fabricated for IMPORT_TEST.
        lic_count = s.query(License).filter_by(project_id="IMPORT_TEST").count()
        check("no licenses created for IMPORT_TEST", lic_count == 0, str(lic_count))

        # The previously-issued /tmp/relink_test.lic still verifies against the
        # derived public key (unchanged). Verify the signature directly with the
        # derived public key PEM.
        from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        import base64

        lic = json.loads(LIC_FILE.read_text())
        payload = f"{lic['fingerprint']}|fp_version:{lic['fp_version']}"
        if lic.get("expires"):
            payload += f"|expires:{lic['expires']}"
        pub = load_pem_public_key(new_key.public_key_pem.encode())
        sig_ok = True
        try:
            pub.verify(base64.b64decode(lic["signature"]), payload.encode(),
                       PKCS1v15(), SHA256())
        except Exception:
            sig_ok = False
        check("relink_test.lic verifies against derived pub key", sig_ok)
        # And via keycheck against the origin private key for good measure.
        check(
            "relink_test.lic matches origin priv (keycheck)",
            keycheck.lic_signature_matches(ORIGIN_PRIV.read_bytes(), lic),
        )

        # Idempotent repair: importing again should UPDATE, not duplicate.
        summary2 = import_key.import_private_key(s, "IMPORT_TEST", priv_copy, version=1)
        s.commit()
        check("second import key_action is updated", summary2["key_action"] == "updated",
              summary2["key_action"])
        check("second import project_created False", summary2["project_created"] is False)
        dup_count = s.query(Key).filter_by(project_id="IMPORT_TEST", version=1).count()
        check("no duplicate key row on re-import", dup_count == 1, str(dup_count))

        # create_project=False against a missing project raises.
        raised = False
        try:
            import_key.import_private_key(s, "NO_SUCH_PROJ", priv_copy,
                                          create_project=False)
        except ValueError:
            raised = True
        check("create_project=False on missing project raises", raised)

        # Non-RSA / unloadable PEM raises ValueError.
        bad = tmp / "bad.pem"
        bad.write_text("not a pem")
        raised2 = False
        try:
            import_key.import_private_key(s, "BAD", bad)
        except ValueError:
            raised2 = True
        check("unloadable PEM raises ValueError", raised2)

    engine.dispose()
    shutil.rmtree(tmp, ignore_errors=True)

    # Real DB must be byte-for-byte unchanged.
    real_sha_after = hashlib.sha256(REGISTRY_DB.read_bytes()).hexdigest()
    check(
        "real registry.db unchanged (sha256)",
        real_sha_before == real_sha_after,
        f"{real_sha_before[:16]} vs {real_sha_after[:16]}",
    )


def main() -> int:
    """Run all tests and report a summary; return non-zero on failure."""
    test_keycheck()
    test_dbmaint()
    test_import_key()
    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
