"""Tests for the new delete/retire/trash dbmaint helpers.

Run with the repo's own environment, e.g.::

    cd /home/suser/simple_license_manager && poetry run python tests/test_delete_features.py

These tests use an in-memory SQLite DB and a temporary filesystem root for the
trash directory, so the real registry.db at ~/.licmgr/registry.db is never
touched and ~/.licmgr/.trash/ stays clean.
"""

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Allow running as a plain script (PYTHONPATH=repo root) or via pytest.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from licmgr.core import dbmaint
from licmgr.core.db.models import Base, Key, License, Project


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


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _fresh_session() -> tuple[Session, Path]:
    """Create an in-memory engine, schema, and an isolated trash data_dir."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    sess = Session(engine, expire_on_commit=False)
    data_dir = Path(tempfile.mkdtemp(prefix="licmgr_test_dd_"))
    return sess, data_dir


def _seed(sess: Session, fs_root: Path) -> dict:
    """Insert two projects, three keys, four licenses; create matching on-disk files.

    Returns a dict of useful paths/ids for assertions.
    """
    now = datetime(2026, 1, 1)
    p1 = Project(
        id="DEMO", display_name="Demo Inc", env_prefix="DEMO",
        version="1.0.0", fp_version=1, validity_days=365, created_at=now,
    )
    p2 = Project(
        id="FOO", display_name="Foo Corp", env_prefix="FOO",
        version="1.0.0", fp_version=1, validity_days=365, created_at=now,
    )
    sess.add_all([p1, p2])
    sess.flush()

    # DEMO has two keys (v1 retired, v2 active); FOO has v1 active.
    demo_keys_dir = fs_root / "projects" / "DEMO" / "keys"
    foo_keys_dir = fs_root / "projects" / "FOO" / "keys"
    demo_keys_dir.mkdir(parents=True)
    foo_keys_dir.mkdir(parents=True)
    (demo_keys_dir / "private_key_v1.pem").write_text("DEMO PRIV v1")
    (demo_keys_dir / "public_key_v1.pem").write_text("DEMO PUB v1")
    (demo_keys_dir / "private_key_v2.pem").write_text("DEMO PRIV v2")
    (demo_keys_dir / "public_key_v2.pem").write_text("DEMO PUB v2")
    (foo_keys_dir / "private_key_v1.pem").write_text("FOO PRIV v1")
    (foo_keys_dir / "public_key_v1.pem").write_text("FOO PUB v1")

    k_demo_1 = Key(
        project_id="DEMO", version=1, algorithm="rsa2048",
        public_key_pem="-----PUB DEMO v1-----", public_key_fp="a" * 64,
        private_key_path=str(demo_keys_dir / "private_key_v1.pem"),
        created_at=now, retired_at=now,
    )
    k_demo_2 = Key(
        project_id="DEMO", version=2, algorithm="rsa2048",
        public_key_pem="-----PUB DEMO v2-----", public_key_fp="b" * 64,
        private_key_path=str(demo_keys_dir / "private_key_v2.pem"),
        created_at=now, retired_at=None,
    )
    k_foo_1 = Key(
        project_id="FOO", version=1, algorithm="rsa2048",
        public_key_pem="-----PUB FOO v1-----", public_key_fp="c" * 64,
        private_key_path=str(foo_keys_dir / "private_key_v1.pem"),
        created_at=now, retired_at=None,
    )
    sess.add_all([k_demo_1, k_demo_2, k_foo_1])
    sess.flush()

    # Licenses: two on DEMO v1 (one revoked, one active), one DEMO v2, one FOO v1.
    lic_dir = fs_root / "licenses_out"
    lic_dir.mkdir()
    paths_lic = {}
    for name in ("demo_v1_acme", "demo_v1_bravo", "demo_v2_charlie", "foo_v1_delta"):
        p = lic_dir / f"{name}.lic"
        p.write_text(f"{{\"client\":\"{name}\"}}")
        paths_lic[name] = p

    lics = [
        License(
            project_id="DEMO", client_name="Acme", machine_fp="f1" * 32,
            fp_version=1, key_version=1, issued_at=now,
            license_json="{}", lic_file_path=str(paths_lic["demo_v1_acme"]),
            revoked=True, revoked_at=now,
        ),
        License(
            project_id="DEMO", client_name="Bravo", machine_fp="f2" * 32,
            fp_version=1, key_version=1, issued_at=now,
            license_json="{}", lic_file_path=str(paths_lic["demo_v1_bravo"]),
        ),
        License(
            project_id="DEMO", client_name="Charlie", machine_fp="f3" * 32,
            fp_version=1, key_version=2, issued_at=now,
            license_json="{}", lic_file_path=str(paths_lic["demo_v2_charlie"]),
        ),
        License(
            project_id="FOO", client_name="Delta", machine_fp="f4" * 32,
            fp_version=1, key_version=1, issued_at=now,
            license_json="{}", lic_file_path=str(paths_lic["foo_v1_delta"]),
        ),
    ]
    sess.add_all(lics)
    sess.flush()
    # Re-fetch IDs (autoincrement).
    lic_ids = {l.client_name: l.id for l in sess.execute(select(License)).scalars()}

    return {
        "fs_root": fs_root,
        "lic_paths": paths_lic,
        "lic_ids": lic_ids,
        "demo_priv_v1": demo_keys_dir / "private_key_v1.pem",
        "demo_pub_v1":  demo_keys_dir / "public_key_v1.pem",
        "demo_priv_v2": demo_keys_dir / "private_key_v2.pem",
        "demo_pub_v2":  demo_keys_dir / "public_key_v2.pem",
        "foo_priv_v1":  foo_keys_dir / "private_key_v1.pem",
        "foo_pub_v1":   foo_keys_dir / "public_key_v1.pem",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_move_to_trash() -> None:
    """move_to_trash: existing paths move, missing are skipped, trash subdir made."""
    print("[move_to_trash]")
    sess, data_dir = _fresh_session()
    try:
        tmp = Path(tempfile.mkdtemp(prefix="licmgr_mtt_"))
        a = tmp / "a.txt"; a.write_text("A")
        b = tmp / "b.txt"; b.write_text("B")
        ghost = tmp / "ghost.txt"  # never created

        trash_dir, moved = dbmaint.move_to_trash([a, b, ghost], label="unit", data_dir=data_dir)
        check("trash_dir created", trash_dir is not None and trash_dir.is_dir())
        check("moved count == 2 (ghost skipped)", len(moved) == 2, str(len(moved)))
        check("a no longer at origin", not a.exists())
        check("b no longer at origin", not b.exists())
        check("a present in trash", any(dst.read_text() == "A" for _, dst in moved))
        check("trash dir under data_dir/.trash", str(trash_dir).startswith(str(data_dir)))

        # Empty input → no work.
        td2, mv2 = dbmaint.move_to_trash([], label="empty", data_dir=data_dir)
        check("empty paths returns (None, [])", td2 is None and mv2 == [])

        # Only-missing paths → no work.
        td3, mv3 = dbmaint.move_to_trash([ghost], label="ghost", data_dir=data_dir)
        check("only-missing paths returns (None, [])", td3 is None and mv3 == [])

        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        sess.close()
        shutil.rmtree(data_dir, ignore_errors=True)


def test_delete_license_with_trash() -> None:
    """delete_license_with_trash: row gone, .lic file trashed; not-found returns None."""
    print("[delete_license_with_trash]")
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_dl_"))
    try:
        seed = _seed(sess, fs_root)
        target_id = seed["lic_ids"]["Acme"]
        target_path = seed["lic_paths"]["demo_v1_acme"]
        check("target .lic exists pre-delete", target_path.is_file())

        report = dbmaint.delete_license_with_trash(sess, target_id, data_dir=data_dir)
        sess.commit()

        check("report not None", report is not None)
        check("report client", report["client"] == "Acme", report["client"])
        check("row gone", sess.get(License, target_id) is None)
        check(".lic file moved away from origin", not target_path.is_file())
        check("trash dir reported", report["trash_dir"] is not None)
        check(".lic file present in trash", any(
            Path(p).is_file() for p in report["moved_files"]
        ))

        # not-found case
        ghost = dbmaint.delete_license_with_trash(sess, 99999, data_dir=data_dir)
        check("not-found returns None", ghost is None)

        # other licenses untouched
        check("Bravo still present", sess.get(License, seed["lic_ids"]["Bravo"]) is not None)
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def test_delete_key_with_trash_cascade() -> None:
    """delete_key_with_trash: key gone, ALL deps (revoked + active) deleted, files trashed."""
    print("[delete_key_with_trash]")
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_dk_"))
    try:
        seed = _seed(sess, fs_root)

        # DEMO v1 has TWO dependent licenses: Acme (revoked) + Bravo (active).
        report = dbmaint.delete_key_with_trash(sess, "DEMO", 1, data_dir=data_dir)
        sess.commit()

        check("report not None", report is not None)
        check("2 dependent licenses removed", len(report["deleted_licenses"]) == 2,
              str(report["deleted_licenses"]))
        check("Key row gone", sess.execute(
            select(Key).where(Key.project_id == "DEMO", Key.version == 1)
        ).scalar_one_or_none() is None)
        check("Acme License row gone",
              sess.get(License, seed["lic_ids"]["Acme"]) is None)
        check("Bravo License row gone",
              sess.get(License, seed["lic_ids"]["Bravo"]) is None)

        # DEMO v2 + its license Charlie untouched.
        check("DEMO v2 Key untouched", sess.execute(
            select(Key).where(Key.project_id == "DEMO", Key.version == 2)
        ).scalar_one_or_none() is not None)
        check("Charlie License untouched",
              sess.get(License, seed["lic_ids"]["Charlie"]) is not None)

        # Files: priv/pub v1 + Acme.lic + Bravo.lic all moved to trash.
        check("DEMO priv v1 file moved", not seed["demo_priv_v1"].exists())
        check("DEMO pub v1 file moved",  not seed["demo_pub_v1"].exists())
        check("Acme .lic moved",  not seed["lic_paths"]["demo_v1_acme"].exists())
        check("Bravo .lic moved", not seed["lic_paths"]["demo_v1_bravo"].exists())
        # And v2 / FOO files untouched.
        check("DEMO priv v2 file untouched", seed["demo_priv_v2"].exists())
        check("FOO priv v1 file untouched",  seed["foo_priv_v1"].exists())

        # not-found case
        ghost = dbmaint.delete_key_with_trash(sess, "DEMO", 99, data_dir=data_dir)
        check("not-found returns None", ghost is None)
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def test_delete_project_with_trash() -> None:
    """delete_project_with_trash: ORM cascade removes keys+licenses; all files trashed."""
    print("[delete_project_with_trash]")
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_dp_"))
    try:
        seed = _seed(sess, fs_root)

        report = dbmaint.delete_project_with_trash(sess, "DEMO", data_dir=data_dir)
        sess.commit()

        check("report not None", report is not None)
        check("Project row gone", sess.get(Project, "DEMO") is None)
        check("2 keys removed", len(report["deleted_keys"]) == 2)
        check("3 licenses removed (Acme, Bravo, Charlie)",
              len(report["deleted_licenses"]) == 3)

        # ORM cascade: all DEMO keys and licenses are gone.
        remaining_demo_keys = sess.execute(
            select(Key).where(Key.project_id == "DEMO")
        ).scalars().all()
        check("no DEMO keys remain", len(remaining_demo_keys) == 0)
        remaining_demo_lics = sess.execute(
            select(License).where(License.project_id == "DEMO")
        ).scalars().all()
        check("no DEMO licenses remain", len(remaining_demo_lics) == 0)

        # FOO untouched (project + key + license).
        check("FOO project untouched", sess.get(Project, "FOO") is not None)
        check("FOO key untouched", sess.execute(
            select(Key).where(Key.project_id == "FOO")
        ).scalar_one_or_none() is not None)
        check("FOO license untouched",
              sess.get(License, seed["lic_ids"]["Delta"]) is not None)

        # All DEMO files moved; FOO files intact.
        check("DEMO priv v1 file moved", not seed["demo_priv_v1"].exists())
        check("DEMO priv v2 file moved", not seed["demo_priv_v2"].exists())
        check("DEMO Acme .lic moved",  not seed["lic_paths"]["demo_v1_acme"].exists())
        check("DEMO Bravo .lic moved", not seed["lic_paths"]["demo_v1_bravo"].exists())
        check("DEMO Charlie .lic moved", not seed["lic_paths"]["demo_v2_charlie"].exists())
        check("FOO priv file intact", seed["foo_priv_v1"].exists())
        check("FOO .lic intact", seed["lic_paths"]["foo_v1_delta"].exists())

        # not-found case
        ghost = dbmaint.delete_project_with_trash(sess, "NOPE", data_dir=data_dir)
        check("not-found returns None", ghost is None)
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def test_retire_key() -> None:
    """retire_key: sets retired_at; second call (already retired) returns False; missing returns False."""
    print("[retire_key]")
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_rk_"))
    try:
        _seed(sess, fs_root)

        # FOO v1 is active; retire it.
        ok = dbmaint.retire_key(sess, "FOO", 1)
        sess.commit()
        check("retire returns True for active key", ok)
        foo_v1 = sess.execute(
            select(Key).where(Key.project_id == "FOO", Key.version == 1)
        ).scalar_one()
        check("FOO v1 retired_at is now set", foo_v1.retired_at is not None)

        # Second call: already retired → False.
        ok2 = dbmaint.retire_key(sess, "FOO", 1)
        check("retire returns False for already-retired key", not ok2)

        # Missing key.
        ok3 = dbmaint.retire_key(sess, "NOPE", 9)
        check("retire returns False for missing key", not ok3)

        # No file should have moved.
        # (We only know retire shouldn't touch the FS, so assert the key file still exists.)
        priv = fs_root / "projects" / "FOO" / "keys" / "private_key_v1.pem"
        check("retire does NOT touch private key file", priv.exists())
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def test_auto_relink_verifies_via_public_key() -> None:
    """auto_relink must match candidate .pem files by deriving public key,
    not just by filename.  Regression test for the 'shared keys_dir relinks
    same file to multiple projects' bug."""
    print("[auto_relink public-key verification]")
    from licmgr.core.generate_keys import generate_key_pair
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_relink_"))
    try:
        # Create two real RSA-2048 key pairs in tempdirs.
        gen_a = fs_root / "gen_a"
        gen_b = fs_root / "gen_b"
        priv_a, pub_a, pem_a, fp_a = generate_key_pair(gen_a, 1)
        priv_b, pub_b, pem_b, fp_b = generate_key_pair(gen_b, 1)
        # Sanity check: the two keys are genuinely different.
        check("two test keys differ", priv_a.read_bytes() != priv_b.read_bytes())

        # Insert two projects, both with a v1 Key whose DB row stores the
        # corresponding public PEM, and whose private_key_path points to a
        # non-existent location (so auto_relink will try to repair it).
        now = datetime(2026, 1, 1)
        sess.add_all([
            Project(id="PROJ_A", display_name="A", env_prefix="A",
                    version="1.0.0", fp_version=1, validity_days=365, created_at=now),
            Project(id="PROJ_B", display_name="B", env_prefix="B",
                    version="1.0.0", fp_version=1, validity_days=365, created_at=now),
        ])
        sess.flush()
        sess.add_all([
            Key(
                project_id="PROJ_A", version=1, algorithm="rsa2048",
                public_key_pem=pem_a, public_key_fp=fp_a,
                private_key_path="/nonexistent/A/private_key_v1.pem",
                created_at=now,
            ),
            Key(
                project_id="PROJ_B", version=1, algorithm="rsa2048",
                public_key_pem=pem_b, public_key_fp=fp_b,
                private_key_path="/nonexistent/B/private_key_v1.pem",
                created_at=now,
            ),
        ])
        sess.flush()

        # Set up a FLAT keys_dir containing ONLY PROJ_A's private key (the
        # user's scenario: drop one .pem into ~/.licmgr/projects/ without a
        # per-project subdir). Filename collides with PROJ_B's expected v1,
        # but its derived public key only matches PROJ_A.
        shared_keys_dir = fs_root / "shared_keys"
        shared_keys_dir.mkdir()
        target_path = shared_keys_dir / "private_key_v1.pem"
        shutil.copy2(priv_a, target_path)

        report = dbmaint.auto_relink(sess, shared_keys_dir)
        sess.commit()

        # PROJ_A should be relinked to the shared .pem.
        proj_a_relinked = next(
            (r for r in report["relinked"] if r["project_id"] == "PROJ_A"), None
        )
        check("PROJ_A relinked", proj_a_relinked is not None,
              f"relinked={report['relinked']}")
        check(
            "PROJ_A new_path is the shared .pem",
            proj_a_relinked and Path(proj_a_relinked["new_path"]).resolve()
                == target_path.resolve(),
            str(proj_a_relinked) if proj_a_relinked else "—",
        )

        # PROJ_B must NOT be relinked — the file's derived public key doesn't
        # match PROJ_B's DB-recorded public PEM, so it stays missing.
        proj_b_relinked = any(r["project_id"] == "PROJ_B" for r in report["relinked"])
        check("PROJ_B NOT relinked (different public key)", not proj_b_relinked,
              f"relinked={report['relinked']}")
        proj_b_missing = any(
            r["project_id"] == "PROJ_B" for r in report["still_missing"]
        )
        check("PROJ_B reported as still_missing", proj_b_missing,
              f"still_missing={report['still_missing']}")

        # And drop PROJ_B's real key into a per-project subdir → second pass
        # should now relink it correctly.
        proj_b_dir = shared_keys_dir / "PROJ_B" / "keys"
        proj_b_dir.mkdir(parents=True)
        shutil.copy2(priv_b, proj_b_dir / "private_key_v1.pem")
        report2 = dbmaint.auto_relink(sess, shared_keys_dir)
        sess.commit()
        b2 = next((r for r in report2["relinked"] if r["project_id"] == "PROJ_B"), None)
        check("PROJ_B relinked on 2nd pass after correct file placed", b2 is not None)
        check(
            "PROJ_B picks the per-project subdir file (not the shared root)",
            b2 and "PROJ_B" in Path(b2["new_path"]).parts,
            str(b2) if b2 else "—",
        )
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def test_dup_fp_guard_query() -> None:
    """Duplicate-fingerprint guard logic: active-only filter, per-project scope.

    Mirrors the SQL that crud.find_licenses_by_fp() uses (the function itself
    opens its own session via the global engine, which is incompatible with
    the test's in-memory session — so we exercise the underlying query
    directly here. The production function is a thin wrapper around exactly
    this select.)
    """
    print("[dup-fp guard]")
    sess, data_dir = _fresh_session()
    fs_root = Path(tempfile.mkdtemp(prefix="licmgr_dupfp_"))
    try:
        _seed(sess, fs_root)
        now = datetime(2026, 2, 1)
        shared_fp = "abcd" * 16  # 64-hex
        sess.add_all([
            License(
                project_id="DEMO", client_name="dup_active_1",
                machine_fp=shared_fp, fp_version=1, key_version=2,
                issued_at=now, license_json="{}", revoked=False,
            ),
            License(
                project_id="DEMO", client_name="dup_revoked_old",
                machine_fp=shared_fp, fp_version=1, key_version=2,
                issued_at=now, license_json="{}",
                revoked=True, revoked_at=now,
            ),
            License(
                project_id="FOO", client_name="foo_same_fp",
                machine_fp=shared_fp, fp_version=1, key_version=1,
                issued_at=now, license_json="{}", revoked=False,
            ),
        ])
        sess.flush()

        def _q(project_id: str, fp: str, only_active: bool = True):
            stmt = select(License).where(
                License.project_id == project_id, License.machine_fp == fp,
            )
            if only_active:
                stmt = stmt.where(License.revoked == False)  # noqa: E712
            return sess.execute(stmt.order_by(License.issued_at.desc())).scalars().all()

        active_in_demo = _q("DEMO", shared_fp)
        check(
            "active dup in DEMO is detected (revoked excluded)",
            len(active_in_demo) == 1 and active_in_demo[0].client_name == "dup_active_1",
            f"got {[(l.client_name, l.revoked) for l in active_in_demo]}",
        )

        all_in_demo = _q("DEMO", shared_fp, only_active=False)
        check("only_active=False returns both active and revoked",
              len(all_in_demo) == 2, str(len(all_in_demo)))

        names_in_demo = {l.client_name for l in all_in_demo}
        check(
            "FOO's same-fp license is NOT returned when scanning DEMO",
            "foo_same_fp" not in names_in_demo,
            str(names_in_demo),
        )
        in_foo = _q("FOO", shared_fp)
        check("FOO's row is detected when scanning FOO", len(in_foo) == 1)

        unknown = _q("DEMO", "0" * 64)
        check("unknown fp returns empty", unknown == [])

        # Sanity: the seeded Bravo row's fp ("f2"*32) is unique → guard does not fire
        no_collision = _q("DEMO", "f2" * 32)
        # Bravo is the only license with that fp in DEMO; guard would see 1 (itself),
        # which IS the correct collision when re-issuing for Bravo's machine.
        check(
            "guard sees the seed's own unique fp as a collision against itself",
            len(no_collision) == 1,
            str(len(no_collision)),
        )
    finally:
        sess.close()
        shutil.rmtree(fs_root, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def main() -> int:
    """Run all tests and report a summary; return non-zero on failure."""
    test_move_to_trash()
    test_delete_license_with_trash()
    test_delete_key_with_trash_cascade()
    test_delete_project_with_trash()
    test_retire_key()
    test_auto_relink_verifies_via_public_key()
    test_dup_fp_guard_query()
    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
