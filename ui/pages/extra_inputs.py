import streamlit as st

from core.offers.facts import derive_facts, make_request, validate_inputs
from core.offers.run import compute_run
from ui.services import get_repo
from ui.steps import go_to

SCORE_PRESETS = {"Excellent (800)": 800, "Good (760)": 760, "Fair (720)": 720, "Low (650)": 650}
SCORE_MODES = ["I'll type my score", "Pick a demo credit profile", "I don't know"]


def render() -> None:
    app = st.session_state["app"]
    d = st.session_state.get("demo_defaults", {})
    st.header("A few more details")
    st.caption("Your documents don't contain these, so we need you to tell us. They are used only to work out indicative offers.")
    st.info("**Self-declared for this demo.** Your existing EMIs and credit score are taken as you enter them. "
            "A real application would check a credit bureau, which needs a licensed partner.")

    with st.form("extra_inputs"):
        c = st.columns(2)
        amount = c[0].text_input("How much do you want to borrow? (₹)", value=str(d.get("amount", "400000")))
        tenure = c[1].text_input("For how many months?", value=str(d.get("tenure", "36")))
        emi = st.text_input("Total of your current monthly EMIs (₹, 0 if none)", value=str(d.get("existing_emi", "0")))
        mode = st.radio("Credit score", SCORE_MODES, index=2 if d.get("credit_score") is None and d else 0, horizontal=True)
        typed = st.text_input("Your credit score (300 to 900)", value=str(d.get("credit_score") or ""))
        preset = st.selectbox("Demo credit profile", list(SCORE_PRESETS), index=2)
        purpose = st.text_input("What is the loan for? (optional, never used to decide)", value=d.get("purpose", ""))
        go = st.form_submit_button("Show my offers", type="primary")

    if go:
        score = {SCORE_MODES[0]: typed, SCORE_MODES[1]: SCORE_PRESETS[preset], SCORE_MODES[2]: None}[mode]
        clean, errors = validate_inputs(amount, tenure, emi, score)
        for msg in errors.values():
            st.error(msg)
        if not errors:
            facts = derive_facts(app, existing_emi=clean["existing_emi"], credit_score=clean["credit_score"])
            if not facts.net_monthly_income or not facts.age:
                st.error("We couldn't work out your income or age from the documents. Please go back and check them.")
                return
            run = compute_run(facts, make_request(clean, purpose))
            get_repo().save_run(app.app_id, run, {"existing_emi": clean["existing_emi"], "credit_score": clean["credit_score"]})
            st.session_state["run"] = run
            st.session_state["demo_defaults"] = {**clean, "purpose": purpose}
            go_to("offers")
    if st.button("Back"):
        go_to("saved")
