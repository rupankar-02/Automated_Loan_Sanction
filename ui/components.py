"""Reusable widgets: status chip, notice banner, field rows, correction form, document card."""
import streamlit as st

from core.config.loader import get_policy
from core.models import FieldResult, FieldStatus
from core.pipeline import clear_slot, remove_part, request_manual_review, submit_correction
from core.state import ApplicationState, Notice, SlotState, slot_status
from core.utils.pii import display_value

CHIPS = {
    "pending": "⚪ Pending", "rejected": "❌ Please re-upload", "needs_attention": "⚠️ Needs attention",
    "verified": "✅ Verified", "manual_review": "🕒 Manual review",
}


def progress_header(ready: int, total: int) -> None:
    st.progress(ready / total if total else 0.0, text=f"{ready} of {total} required documents ready")


def notice_banner(n: Notice) -> None:
    text = f"**{n.message}**" + (f"  \n{n.fix_hint}" if n.fix_hint else "")
    (st.error if n.severity == "error" else st.warning)(text, icon="❌" if n.severity == "error" else "⚠️")


def field_row(f: FieldResult) -> None:
    ok = f.status in (FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID)
    value = display_value(f.key, f.normalized_value or f.raw_value, validated=ok)
    if f.status in (FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID):
        src = " _(entered by you)_" if f.source == "user" else ""
        st.markdown(f"✅ **{f.label}:** {value}{src}")
        if f.warning:
            st.caption(f"⚠️ {f.warning}")
    elif f.status == FieldStatus.INVALID:
        st.markdown(f"❌ **{f.label}:** {value}")
        st.caption(f"{f.message}")
    elif f.status == FieldStatus.NEEDS_MANUAL_REVIEW:
        st.markdown(f"🕒 **{f.label}:** will be checked by a person")
    else:
        mark = "❓" if f.required else "➖"
        st.markdown(f"{mark} **{f.label}:** not found" + ("" if f.required else " _(optional)_"))


def correction_form(state: ApplicationState, slot: SlotState, pi: int) -> None:
    part = slot.parts[pi]
    todo = [f for f in part.fields if f.status in (FieldStatus.NOT_EXTRACTED, FieldStatus.INVALID) and f.required]
    if not todo:
        return
    cap = get_policy().retries.max_field_attempts
    with st.form(f"fix_{slot.slot_id}_{pi}"):
        st.markdown("**Please enter or correct these:**")
        for f in todo:
            st.text_input(f"{f.label}  ·  {cap - f.attempts} tries left", key=f"in_{slot.slot_id}_{pi}_{f.key}")
        if st.form_submit_button("Check my entries"):
            for f in todo:
                v = st.session_state.get(f"in_{slot.slot_id}_{pi}_{f.key}", "").strip()
                if v:
                    submit_correction(state, slot.slot_id, pi, f.key, v)
            st.rerun()


def _bump(slot_id: str) -> None:
    ver = st.session_state.setdefault("uploader_ver", {})
    ver[slot_id] = ver.get(slot_id, 0) + 1


def document_card(state: ApplicationState, slot: SlotState) -> list[tuple[str, str, bytes]]:
    """Render one slot. Returns the new uploads (slot_id, filename, bytes) found this run."""
    status = slot_status(slot)
    ver = st.session_state.setdefault("uploader_ver", {}).get(slot.slot_id, 0)
    multi = slot.required_parts > 1
    jobs: list[tuple[str, str, bytes]] = []

    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].markdown(f"#### {slot.label}" + ("  _(optional)_" if slot.optional else ""))
        top[1].markdown(CHIPS[status])
        st.caption(slot.spec.description)

        if slot.notice:
            notice_banner(slot.notice)
            if slot.notice.offer_manual_review and not slot.manual_review:
                if st.button("Continue and send this for manual review", key=f"mr_{slot.slot_id}"):
                    request_manual_review(state, slot.slot_id)
                    st.rerun()

        for pi, part in enumerate(slot.parts):
            if part.pages == 0:
                continue
            with st.expander(f"{part.file_name}" + (f" · {part.pages} pages" if part.pages > 1 else ""), expanded=status != "verified"):
                if part.extraction_failed:
                    st.warning("We couldn't read this document automatically, so please type the details below.")
                    if part.error:
                        st.caption(f"Reason: {part.error}")
                for f in part.fields:
                    field_row(f)
                for i in part.issues:
                    (st.error if i.severity == "error" else st.warning)(
                        i.message + ("  \n**Next step:** upload a corrected document below." if i.action == "reupload" and i.severity == "error" else ""))
                correction_form(state, slot, pi)
                if multi and st.button("Remove this slip", key=f"rm_{slot.slot_id}_{pi}"):
                    remove_part(state, slot.slot_id, pi)
                    st.rerun()
        for i in slot.set_issues:
            st.error(i.message + "  \n**Next step:** remove the wrong slip and upload the right one.")

        if slot.extractable:
            need = slot.required_parts - len(slot.parts)
            if multi and need > 0 and slot.parts:
                st.info(f"Upload {need} more salary slip{'s' if need > 1 else ''}.")
            if slot.parts and not multi and st.button("Replace this document", key=f"rep_{slot.slot_id}"):
                clear_slot(state, slot.slot_id)
                _bump(slot.slot_id)
                st.rerun()
            if multi or not slot.parts:
                types = ["jpg", "jpeg", "png", "pdf"]
                up = st.file_uploader("Upload file" + ("s (one per month, or one PDF)" if multi else ""), type=types,
                                      accept_multiple_files=multi, key=f"up_{slot.slot_id}_{ver}")
                files = up if multi else ([up] if up else [])
                with st.expander("Take a photo instead"):
                    cam = st.camera_input("Camera", key=f"cam_{slot.slot_id}_{ver}", label_visibility="collapsed")
                if cam:
                    files = list(files) + [cam]
                for f in files:
                    jobs.append((slot.slot_id, getattr(f, "name", "photo.jpg") or "photo.jpg", f.getvalue()))
        else:
            st.caption("Automatic reading for this document is coming soon. You can skip it for now.")
    return jobs
