"""Headless UI smoke test: consent -> loan -> employment -> checklist renders."""
from streamlit.testing.v1 import AppTest


def test_wizard_reaches_checklist():
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    at.checkbox[0].check().run()
    at.button[0].click().run()                       # consent -> loan type
    assert at.header[0].value.startswith("What kind of loan")
    at.button[1].click().run()                       # personal loan -> employment
    assert at.header[0].value.startswith("How do you earn")
    at.button[1].click().run()                       # salaried -> checklist
    assert not at.exception, at.exception
    assert at.header[0].value == "Your document checklist"
    titles = " ".join(m.value for m in at.markdown)
    for label in ("PAN Card", "Aadhaar Card (front)", "Aadhaar Card (back)", "Salary Slip", "Bank Statement", "Form 16 or ITR"):
        assert label in titles


def test_review_save_and_delete(tmp_path, monkeypatch):
    import streamlit as st
    from cryptography.fernet import Fernet
    from core.config.settings import get_settings
    from core.storage import FileStore
    from tests.helpers import AADHAAR_NO, PAN_NO, build_ready_app

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    st.cache_resource.clear()
    store = FileStore(tmp_path / "uploads")
    app = build_ready_app(store)

    at = AppTest.from_file("../app.py", default_timeout=30)
    at.session_state["app"] = app
    at.session_state["step"] = "review"
    at.run()
    assert not at.exception, at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "ABCDE****F" in page and PAN_NO not in page and AADHAAR_NO not in page      # masked by default

    at.toggle[0].set_value(True).run()
    assert PAN_NO in " ".join(m.value for m in at.markdown)                            # shown only on request
    assert next(b for b in at.button if b.label == "Save and continue").disabled        # needs the confirmation tick

    at.checkbox[0].check().run()
    next(b for b in at.button if b.label == "Save and continue").click().run()
    assert not at.exception, at.exception
    assert at.success[0].value.startswith("Your documents are verified") and app.status == "saved"
    assert store.count(app.app_id) == 0

    at.sidebar.expander[0].checkbox[0].check().run()
    next(b for b in at.sidebar.button if b.label == "Delete my documents and data").click().run()
    assert not at.exception, at.exception
    assert "app" not in at.session_state
    assert at.title[0].value == "Document Copilot"                                        # back at the start
