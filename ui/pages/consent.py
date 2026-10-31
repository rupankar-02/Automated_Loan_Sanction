from datetime import datetime, timezone

import streamlit as st

from core.demo import PROFILES, load_demo_application
from ui.services import get_repo
from ui.steps import go_to


def render() -> None:
    st.title("Document Copilot")
    st.subheader("Get your loan documents right the first time")
    st.markdown(
        "We check each document **before** you submit it, tell you exactly what to fix, and prepare a "
        "clean file for your loan application. We don't approve or reject loans."
    )
    st.info(
        "**How your documents are handled**\n\n"
        "- Your document images are sent to external AI services to read them: **Google Gemini** "
        "(identifies the document type) and **Sarvam AI** (reads the details).\n"
        "- Aadhaar and account numbers are shown and stored masked.\n"
        "- You can delete your documents at any time.\n"
        "- **This is a prototype: use dummy or sample documents only, not real ones.**"
    )
    ok = st.checkbox("I understand, and I agree to my documents being processed this way.")
    if st.button("Continue", type="primary", disabled=not ok):
        st.session_state["consent_at"] = datetime.now(timezone.utc)
        go_to("loan_type")

    st.divider()
    with st.expander("Demo mode: try a sample applicant (no real documents)"):
        st.caption("Loads a fictional, already-verified applicant so you can go straight to the loan offers. "
                   "No documents are uploaded and no AI is called for them.")
        for key, p in PROFILES.items():
            if st.button(f"{p.title}: {p.blurb}", key=f"demo_{key}", use_container_width=True):
                state, prof = load_demo_application(key, get_repo())
                for k in ("run", "chat", "lender_pkg", "kyc_session"):
                    st.session_state.pop(k, None)
                st.session_state.update({"app": state, "seen": set(), "demo_defaults": {
                    "amount": prof.amount, "tenure": prof.tenure, "existing_emi": prof.existing_emi,
                    "credit_score": prof.credit_score, "purpose": ""}})
                go_to("extra_inputs")
