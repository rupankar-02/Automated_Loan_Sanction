import json

import pytest
from cryptography.fernet import Fernet

from core.db.repo import Repo
from core.kyc.mock import MockKYCProvider
from core.models import FieldStatus
from core.pipeline import submit_correction
from core.save import NotReady, confirm_and_save
from core.state import new_application
from core.storage import FileStore
from core.utils.crypto import FieldCipher
from core.utils.pii import display_value, mask_pan, mask_tail, protect_value
from tests.helpers import AADHAAR_NO, ACCOUNT_NO, CTX, PAN_NO, build_ready_app


@pytest.fixture
def env(tmp_path):
    cipher = FieldCipher(Fernet.generate_key())
    store = FileStore(tmp_path / "uploads")
    repo = Repo(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}", cipher, store)
    return repo, store, cipher


def test_masking_helpers():
    assert mask_tail("234567890123") == "XXXXXXXX0123"
    assert mask_pan("ABCDE1234F") == "ABCDE****F"
    assert display_value("pan_number", "ABCDE1234F") == "ABCDE****F"
    assert display_value("pan_number", "ABCDE1234F", reveal=True) == "ABCDE1234F"
    assert display_value("pan_number", "ABCD1234F", validated=False) == "ABCD1234F"      # shown so it can be corrected
    assert display_value("aadhaar_number", "234567890123", reveal=True) == "XXXXXXXX0123"   # never revealed
    assert display_value("name", "RAHUL SHARMA") == "RAHUL SHARMA"


def test_protect_value_masks_raw_and_encrypts_pan(env):
    _, _, cipher = env
    stored, h = protect_value("pan_number", PAN_NO, cipher)
    assert PAN_NO not in stored and stored.startswith("enc:") and cipher.decrypt(stored) == PAN_NO
    assert h == cipher.keyed_hash(PAN_NO.lower())            # case-insensitive match key
    assert protect_value("aadhaar_number", "2345 6789 0123", cipher) == ("XXXXXXXX0123", None)
    assert protect_value("name", "RAHUL", cipher) == ("RAHUL", None)


def test_nothing_sensitive_is_stored_in_full(env):
    repo, store, _ = env
    app = build_ready_app(store)
    repo.sync(app, "review")
    dump = repo.dump_text()
    assert PAN_NO not in dump and AADHAAR_NO not in dump and ACCOUNT_NO not in dump
    assert "XXXXXXXX" + AADHAAR_NO[-4:] in dump              # masked form is what is kept
    assert "enc:" in dump                                    # the PAN is there, encrypted
    # the model's raw value is masked too, not just the normalised one
    from sqlalchemy import select
    from core.db.models import FieldRow
    with repo.Session() as s:
        raw = {f.field_key: f.raw_value for f in s.scalars(select(FieldRow))}
    assert raw["aadhaar_number"] == "XXXXXXXX" + AADHAAR_NO[-4:] and raw["account_number"].endswith(ACCOUNT_NO[-4:])
    assert "X" in raw["account_number"] and ACCOUNT_NO not in raw["account_number"]


def test_audit_trail_has_no_values(env):
    repo, store, _ = env
    app = build_ready_app(store)
    submit_correction(app, "pan", 0, "pan_number", PAN_NO, CTX)     # a user edit gets logged
    repo.sync(app, "review")
    trail = json.dumps(repo.audit_trail(app.app_id))
    for secret in (PAN_NO, AADHAAR_NO, ACCOUNT_NO, "RAHUL"):
        assert secret not in trail
    assert "user_edit" in trail and "pan_number" in trail            # field key and status only


def test_resync_is_idempotent_and_updates(env):
    repo, store, _ = env
    app = build_ready_app(store)
    repo.sync(app, "review")
    repo.sync(app)
    pkg = repo.export_package(app.app_id)
    assert len([d for d in pkg["documents"] if d["slot"] == "salary_slip"]) == 3
    assert repo.audit_trail(app.app_id).count is not None
    events = [e["event"] for e in repo.audit_trail(app.app_id)]
    assert len(events) == len(app.events)                             # each event written once


def test_confirm_and_save_flow(env):
    repo, store, _ = env
    app = build_ready_app(store)
    assert store.count(app.app_id) == 7                              # originals kept until confirmation
    pkg = confirm_and_save(app, repo)
    assert app.status == "saved" and app.scrubbed
    assert store.count(app.app_id) == 0                              # originals purged
    assert all(d["file_name"] for d in pkg["documents"])
    # memory is scrubbed too
    pan = next(f for p in app.slots["pan"].parts for f in p.fields if f.key == "pan_number")
    aad = next(f for p in app.slots["aadhaar_front"].parts for f in p.fields if f.key == "aadhaar_number")
    assert pan.normalized_value == "ABCDE****F" and pan.raw_value == "ABCDE****F"
    assert aad.normalized_value.startswith("XXXXXXXX") and aad.raw_value.startswith("XXXXXXXX")
    # a later sync must not overwrite the encrypted PAN with the masked one
    repo.sync(app)
    assert repo.export_package(app.app_id, "lender")["applicant"]["pan"] == PAN_NO
    from sqlalchemy import select
    from core.db.models import DocumentRow
    with repo.Session() as s:
        assert all(d.storage_path is None for d in s.scalars(select(DocumentRow)))
    events = [e["event"] for e in repo.audit_trail(app.app_id)]
    assert {"confirmed", "files_purged", "saved"} <= set(events)


def test_save_requires_a_ready_application(env):
    repo, _, _ = env
    with pytest.raises(NotReady):
        confirm_and_save(new_application("personal", "salaried"), repo)


def test_export_modes(env):
    repo, store, _ = env
    app = build_ready_app(store)
    confirm_and_save(app, repo)
    user, lender = repo.export_package(app.app_id, "user"), repo.export_package(app.app_id, "lender")
    assert user["applicant"]["pan"] == "ABCDE****F" and lender["applicant"]["pan"] == PAN_NO
    assert PAN_NO not in json.dumps(user)
    for pkg in (user, lender):
        assert AADHAAR_NO not in json.dumps(pkg) and ACCOUNT_NO not in json.dumps(pkg)
        assert pkg["applicant"]["aadhaar"] == "XXXXXXXX" + AADHAAR_NO[-4:]
    assert user["applicant"]["name"] == "RAHUL SHARMA" and user["applicant"]["dob"] == "1990-08-15"
    with pytest.raises(ValueError):
        repo.export_package(app.app_id, "everything")


def test_manual_review_items_are_exported(env):
    repo, store, _ = env
    app = build_ready_app(store)
    for _ in range(3):
        pass
    from core.pipeline import request_manual_review
    app.slots["bank_statement"].parts[0].fields[3] = app.slots["bank_statement"].parts[0].fields[3].model_copy(
        update={"status": FieldStatus.NEEDS_MANUAL_REVIEW})
    app.manual_review_ack = True
    pkg = confirm_and_save(app, repo)
    assert pkg["manual_review"] == ["bank_statement:ifsc"]


def test_delete_removes_everything_but_a_bare_audit_row(env):
    repo, store, _ = env
    app = build_ready_app(store)
    repo.sync(app, "review")
    repo.save_kyc(app.app_id, "k1", "mock", "completed", {"steps": ["otp"]}, True)
    assert store.count(app.app_id) == 7
    counts = repo.delete_application(app.app_id)
    assert counts["files"] == 7 and counts["extracted_fields"] > 0 and counts["kyc_sessions"] == 1
    assert store.count(app.app_id) == 0
    dump = repo.dump_text()
    for secret in (PAN_NO, AADHAAR_NO, ACCOUNT_NO, "enc:", "RAHUL", "HDFC", "560001", "XXXXXXXX"):
        assert secret not in dump, secret
    trail = repo.audit_trail(app.app_id)
    assert [e["event"] for e in trail] == ["application_deleted"] and trail[0]["payload"] == {}
    with pytest.raises(KeyError):
        repo.export_package(app.app_id)


def test_delete_after_save_leaves_no_pan(env):
    repo, store, _ = env
    app = build_ready_app(store)
    confirm_and_save(app, repo)
    repo.delete_application(app.app_id)
    assert "enc:" not in repo.dump_text() and store.count(app.app_id) == 0


def test_stale_uploads_are_purged_by_age(tmp_path):
    import os, time
    store = FileStore(tmp_path / "u")
    store.save("old", "h1", b"x")
    store.save("new", "h2", b"y")
    old = time.time() - 48 * 3600
    os.utime(tmp_path / "u" / "old", (old, old))
    assert store.purge_older_than(24) == 1
    assert store.count("old") == 0 and store.count("new") == 1


def test_kyc_mock(env):
    app = build_ready_app()
    kyc = MockKYCProvider()
    items = {i.label: i for i in kyc.readiness(app)}
    assert all(i.ok for i in items.values()) and len(items) == 4
    s = kyc.start(app.app_id)
    assert not kyc.verify_otp(s, "12ab") and kyc.verify_otp(s, "123456")
    assert kyc.complete(s, selfie_captured=False).status == "failed"
    s2 = kyc.start(app.app_id)
    kyc.verify_otp(s2, "654321")
    assert kyc.complete(s2, selfie_captured=True).status == "completed"
