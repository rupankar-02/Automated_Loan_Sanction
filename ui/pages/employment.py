import streamlit as st

from core.requirements import EMPLOYMENT_TYPES, supported_profiles
from core.state import new_application
from ui.steps import go_to


def render() -> None:
    st.header("How do you earn your income?")
    loan = st.session_state["loan_type"]
    supported = supported_profiles().get(loan, [])
    labels = {k: v + ("" if k in supported else "  (coming soon)") for k, v in EMPLOYMENT_TYPES.items()}
    choice = st.radio("Employment type", list(labels), format_func=labels.get, key="emp_choice")
    if choice not in supported:
        st.warning("Documents for this option aren't available yet. Please choose Salaried for now.")
    c = st.columns(2)
    if c[0].button("Back"):
        go_to("loan_type")
    if c[1].button("Show my checklist", type="primary", disabled=choice not in supported):
        app = new_application(loan, choice)
        app.consent_at = st.session_state.get("consent_at")
        app.log("consent_given")
        st.session_state["app"] = app
        st.session_state["seen"] = set()
        go_to("upload")
