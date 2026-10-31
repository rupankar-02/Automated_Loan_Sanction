import time
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from core.config.loader import get_policy
from core.pipeline import process_many
from core.state import progress, readiness
from core.utils.hashing import sha256_bytes
from ui.components import document_card, progress_header
from ui.services import get_store, persist
from ui.steps import go_to


def _run(app, jobs, extractor) -> None:
    """Process new uploads in a worker thread; the main thread paints per-document progress."""
    msgs: dict[str, str] = {sid: "Waiting..." for sid, _, _ in jobs}
    with st.status("Checking your documents...", expanded=True) as box:
        slots = {sid: st.empty() for sid in msgs}
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(process_many, app, jobs, extractor, lambda sid, m: msgs.__setitem__(sid, m), None, get_store())
            while not fut.done():
                for sid, ph in slots.items():
                    ph.markdown(f"**{app.slots[sid].label}:** {msgs[sid]}")
                time.sleep(0.3)
            fut.result()
        for sid, ph in slots.items():
            ph.markdown(f"**{app.slots[sid].label}:** done")
        box.update(label="Checks finished", state="complete", expanded=False)
    ver = st.session_state.setdefault("uploader_ver", {})
    for sid in msgs:                       # clear the uploaders; results live in the cards
        ver[sid] = ver.get(sid, 0) + 1


def render(extractor) -> None:
    app = st.session_state["app"]
    st.header("Your document checklist")
    ready, total = progress(app)
    progress_header(ready, total)
    st.caption(f"Checks used: {app.api_calls} of {get_policy().limits.max_api_calls_per_application}")

    seen: set = st.session_state.setdefault("seen", set())
    jobs = []
    for slot in app.slots.values():
        for sid, name, data in document_card(app, slot):
            key = (sid, sha256_bytes(data))
            if key not in seen:
                seen.add(key)
                jobs.append((sid, name, data))
    if jobs:
        _run(app, jobs, extractor)
        persist(app)
        st.rerun()
    persist(app)                           # checkpoint corrections, removals and manual-review requests

    ok, problems = readiness(app)
    st.divider()
    if problems:
        with st.expander(f"Still to do ({len(problems)})", expanded=False):
            for p in problems:
                st.markdown(f"- {p}")
    if any(s.manual_review or any(f.status.value == "needs_manual_review" for p in s.parts for f in p.fields)
           for s in app.slots.values()):
        app.manual_review_ack = st.checkbox(
            "I understand some details will be sent for manual review.", value=app.manual_review_ack)
    c = st.columns(2)
    if c[0].button("Back"):
        go_to("employment")
    if c[1].button("Review my details", type="primary", disabled=not ok):
        go_to("review")
