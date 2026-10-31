import streamlit as st

from core.models import FieldStatus
from core.pipeline import submit_correction
from core.requirements import EMPLOYMENT_TYPES, LOAN_TYPES
from core.save import NotReady, confirm_and_save
from core.state import all_fields, readiness, slot_status
from core.utils.pii import display_value
from ui.services import get_repo
from ui.steps import go_to

_OK = (FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID)


def _first(app, slot_id, key):
    slot = app.slots.get(slot_id)
    f = next((f for p in (slot.parts if slot else []) for f in p.fields if f.key == key), None)
    return f.normalized_value if f else None


def _edit_box(app, slot) -> None:
    editable = [(pi, f) for pi, p in enumerate(slot.parts) for f in p.fields if f.status != FieldStatus.NEEDS_MANUAL_REVIEW]
    if not editable:
        return
    with st.expander("Something wrong? Edit a value"):
        opts = {f"{f.label}" + (f" (document {pi + 1})" if len(slot.parts) > 1 else ""): (pi, f.key) for pi, f in editable}
        with st.form(f"edit_{slot.slot_id}"):
            pick = st.selectbox("Field", list(opts), key=f"pick_{slot.slot_id}")
            val = st.text_input("Correct value", key=f"val_{slot.slot_id}")
            if st.form_submit_button("Save change") and val.strip():
                pi, key = opts[pick]
                res = submit_correction(app, slot.slot_id, pi, key, val.strip())
                st.session_state["edit_msg"] = (res.status in _OK, res.message or "Updated.")
                st.rerun()


def render() -> None:
    app = st.session_state["app"]
    st.header("Review and confirm")
    st.caption("Check every detail. Anything wrong can be edited before you confirm.")
    if msg := st.session_state.pop("edit_msg", None):
        (st.success if msg[0] else st.error)("Updated." if msg[0] else msg[1])

    reveal = st.toggle("Show my full PAN", value=False)
    pan = _first(app, "pan", "pan_number")
    with st.container(border=True):
        st.markdown("**Applicant**")
        st.markdown(f"- Loan: {LOAN_TYPES.get(app.loan_type)}  ·  Employment: {EMPLOYMENT_TYPES.get(app.employment)}")
        st.markdown(f"- Name: {_first(app, 'pan', 'name') or '-'}  ·  Date of birth: {_first(app, 'pan', 'dob') or '-'}")
        st.markdown(f"- PAN: {display_value('pan_number', pan, reveal=reveal) or '-'}  ·  "
                    f"Aadhaar: {display_value('aadhaar_number', _first(app, 'aadhaar_front', 'aadhaar_number')) or '-'}")

    warnings = []
    for slot in app.slots.values():
        if not slot.parts and not slot.manual_review:
            continue
        with st.container(border=True):
            st.markdown(f"**{slot.label}**  ·  {'✅ verified' if slot_status(slot) == 'verified' else '🕒 manual review'}")
            for pi, part in enumerate(slot.parts):
                if part.pages == 0:
                    continue
                if len(slot.parts) > 1:
                    st.caption(part.file_name)
                for f in part.fields:
                    if f.status in _OK:
                        badge = "entered by you" if f.source == "user" else "from document"
                        v = display_value(f.key, f.normalized_value, reveal=reveal) or "-"
                        st.markdown(f"- {f.label}: **{v}**  `{badge}`")
                        if f.warning:
                            warnings.append(f"{slot.label}: {f.warning}")
                    elif f.status == FieldStatus.NEEDS_MANUAL_REVIEW:
                        st.markdown(f"- {f.label}: 🕒 _will be checked by a person_")
                    elif f.required:
                        st.markdown(f"- {f.label}: ❌ _missing_")
                warnings += [f"{slot.label}: {i.message}" for i in part.issues if i.severity == "warning"]
                warnings += [f"{slot.label}: {w.message}" for w in part.quality_warnings]
            _edit_box(app, slot)

    st.markdown("**Checklist**")
    for slot in app.slots.values():
        if slot.optional and not slot.parts:
            continue
        st.markdown(f"- {'✔' if slot_status(slot) in ('verified', 'manual_review') else '✖'} {slot.label}")
    if warnings:
        with st.expander(f"Notes that don't block you ({len(warnings)})"):
            for w in warnings:
                st.markdown(f"- {w}")

    ok, problems = readiness(app)
    for p in problems:
        st.error(p)
    confirmed = st.checkbox("I confirm these details are correct.")
    c = st.columns(2)
    if c[0].button("Back to documents"):
        go_to("upload")
    if c[1].button("Save and continue", type="primary", disabled=not (ok and confirmed)):
        try:
            confirm_and_save(app, get_repo())
        except NotReady as e:
            st.error(str(e))
        else:
            go_to("saved")
