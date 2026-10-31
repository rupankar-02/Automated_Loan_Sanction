import streamlit as st

from core.kyc.mock import MockKYCProvider
from ui.handoff import handoff_block
from ui.services import get_repo
from ui.steps import go_to


def render() -> None:
    app = st.session_state["app"]
    repo, kyc = get_repo(), MockKYCProvider()
    st.header("Identity check")
    sel = repo.selected_offer(app.app_id)
    if sel:
        from core.offers.catalog import get_catalog
        st.success(f"You selected: **{get_catalog().offer(sel).name}**")
    st.warning("**Demo mode.** Real Aadhaar eKYC, CKYC and video-KYC need regulated partners. "
               "Here the OTP and face match are simulated: any 6-digit code works and no face is compared.")

    st.markdown("**Already verified from your documents**")
    for item in kyc.readiness(app):
        st.markdown(f"- {'✅' if item.ok else '⚠️'} {item.label}" + (f"  _({item.note})_" if item.note else ""))

    session = st.session_state.get("kyc_session")
    if session is None:
        agree = st.checkbox("I consent to my identity being verified.")
        if st.button("Start identity check", type="primary", disabled=not agree):
            session = kyc.start(app.app_id)
            st.session_state["kyc_session"] = session
            repo.save_kyc(app.app_id, session.session_id, session.method, "started", {"demo": True}, False)
            app.log("kyc_started")
            repo.sync(app, "kyc_started")
            st.rerun()
        return

    if "otp" not in session.steps_done:
        st.markdown("**Step 1 - Aadhaar OTP** _(demo)_")
        code = st.text_input("Enter any 6-digit code", max_chars=6)
        if st.button("Verify code"):
            if kyc.verify_otp(session, code):
                st.rerun()
            st.error("Enter a 6-digit code.")
        return

    if session.status != "completed":
        st.markdown("**Step 2 - Selfie** _(demo: the photo is not stored or compared)_")
        shot = st.camera_input("Take a selfie")
        if shot and st.button("Finish", type="primary"):
            kyc.complete(session, selfie_captured=True)
            repo.save_kyc(app.app_id, session.session_id, session.method, session.status,
                          {"demo": True, "steps": session.steps_done}, True)
            app.log("kyc_done")
            repo.sync(app, "kyc_done")
            st.rerun()
        return

    st.success("Identity check complete (demo). Your application file is ready for the lender.")
    handoff_block(app)
    if st.button("Back to summary"):
        go_to("saved")
