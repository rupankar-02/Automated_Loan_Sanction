"""Document Copilot - Streamlit entry. Run: streamlit run app.py"""
import os

import streamlit as st

# Streamlit Cloud secrets -> environment variables (locally the .env file is used instead).
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)):
            os.environ.setdefault(str(_k), str(_v))
except Exception:
    pass                      # no secrets file locally

# The server starts with an empty disk: create what the app expects.
os.makedirs("data/uploads", exist_ok=True)

from core.config.settings import get_settings
from core.extraction import get_extractor
from core.vlm.registry import list_models
from core.vlm.roles import LiveExtractor
from ui import steps
from ui.pages import consent, employment, extra_inputs, kyc, loan_type, offers, review, saved, upload
from ui.services import get_repo

st.set_page_config(page_title="Document Copilot", page_icon="📄", layout="wide")


def sidebar_model_picker() -> str:
    """Gemini model used for the document-type check. Sarvam Vision always does the extraction."""
    opts = [m for m in list_models(vision_only=True) if m.provider == "gemini"]
    keys = [m.key for m in opts]
    default = get_settings().default_model
    st.sidebar.markdown("---")
    return st.sidebar.selectbox(
        "AI model (document check)", keys, index=keys.index(default) if default in keys else 0,
        format_func=lambda k: next(m.label for m in opts if m.key == k),
        help="Reading the details is always done by Sarvam Vision.")


def sidebar_privacy() -> None:
    """Delete-my-data control. Scope is stated on the button, as promised in the consent text."""
    app = st.session_state.get("app")
    if app is None:
        return
    with st.sidebar.expander("Privacy"):
        st.caption("**Delete my documents and data** removes your uploaded files, all extracted details "
                   "(including the encrypted PAN), validation results and identity-check data. "
                   "Only a record that this application was deleted remains, with no personal details.")
        sure = st.checkbox("Yes, delete everything for this application", key="del_ok")
        if st.button("Delete my documents and data", disabled=not sure):
            get_repo().delete_application(app.app_id)
            for k in ("app", "seen", "kyc_session", "lender_pkg", "uploader_ver", "consent_at", "step", "run", "chat", "demo_defaults"):
                st.session_state.pop(k, None)
            st.session_state["deleted"] = True
            st.rerun()


steps.stepper()


def sidebar_service_check() -> None:
    """Shows whether the AI services are configured and reachable. Never shows a key."""
    s = get_settings()
    with st.sidebar.expander("Service check"):
        st.markdown(f"- Sarvam key: {'set' if s.sarvam_api_key else '**missing**'}\n"
                    f"- Gemini key: {'set' if s.gemini_api_key else '**missing**'}"
                    f"{' (+ second key)' if s.gemini_api_key2 else ''}\n- Type check: {s.classifier}")
        if st.button("Test document reading", key="svc_test"):
            from PIL import Image, ImageDraw, ImageFont
            from core.vlm.sarvam_doc import SarvamVisionExtractor
            img = Image.new("RGB", (900, 300), "white")
            try:
                f = ImageFont.truetype("DejaVuSans.ttf", 56)
            except OSError:
                f = ImageFont.load_default()
            ImageDraw.Draw(img).text((40, 100), "ABCPE1234F", fill="black", font=f)
            try:
                out = SarvamVisionExtractor().extract([{"key": "pan_number", "description": "the 10-character PAN, exactly as printed"}], images=[img])
                st.success(f"Reading works: {out}")
            except Exception as e:
                st.error(f"{type(e).__name__}: {str(e)[:300]}")


st.sidebar.caption("Prototype: please use the dummy documents from the demo_data folder, not real ones.")
sidebar_privacy()
sidebar_service_check()
if st.session_state.pop("deleted", False):
    st.sidebar.success("Everything for that application has been deleted.")
model_key = sidebar_model_picker()
extractor = get_extractor() if get_settings().use_mock_vlm else LiveExtractor(model_key)

step = steps.current()
if step in ("upload", "review", "saved", "extra_inputs", "offers", "kyc") and "app" not in st.session_state:
    steps.go_to("consent")
elif step == "consent":
    consent.render()
elif step == "loan_type":
    loan_type.render()
elif step == "employment":
    employment.render()
elif step == "upload":
    upload.render(extractor)
elif step == "review":
    review.render()
elif step == "saved":
    saved.render()
elif step == "kyc":
    kyc.render()
elif step == "extra_inputs":
    extra_inputs.render()
elif step == "offers":
    offers.render(model_key)
