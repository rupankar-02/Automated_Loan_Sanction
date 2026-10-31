"""Step machine on top of st.session_state."""
import streamlit as st

STEPS = [("consent", "Consent"), ("loan_type", "Loan type"), ("employment", "Employment"),
         ("upload", "Documents"), ("review", "Review & confirm"), ("saved", "Saved"),
         ("extra_inputs", "More details"), ("offers", "Offers"), ("kyc", "Identity check")]
_IDS = [s for s, _ in STEPS]


def current() -> str:
    return st.session_state.setdefault("step", "consent")


def go_to(step: str) -> None:
    st.session_state["step"] = step
    st.rerun()


def stepper() -> None:
    cur = _IDS.index(current())
    for i, (_, label) in enumerate(STEPS):
        mark = "✅" if i < cur else ("🔵" if i == cur else "⚪")
        st.sidebar.markdown(f"{mark} {label}")
