import streamlit as st

from core.requirements import LOAN_TYPES, supported_profiles
from ui.steps import go_to


def render() -> None:
    st.header("What kind of loan do you need?")
    supported = supported_profiles()
    labels = {k: v + ("" if k in supported else "  (coming soon)") for k, v in LOAN_TYPES.items()}
    choice = st.radio("Loan type", list(labels), format_func=labels.get, key="loan_choice")
    if choice not in supported:
        st.warning("This loan type isn't available yet. Please choose Personal loan for now.")
    c = st.columns(2)
    if c[0].button("Back"):
        go_to("consent")
    if c[1].button("Continue", type="primary", disabled=choice not in supported):
        st.session_state["loan_type"] = choice
        go_to("employment")
