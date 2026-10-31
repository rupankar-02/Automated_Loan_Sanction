import json

import streamlit as st

from ui.handoff import handoff_block
from ui.services import get_repo
from ui.steps import go_to


def render() -> None:
    app = st.session_state["app"]
    repo = get_repo()
    st.success("Your documents are verified and saved.")
    st.markdown(
        "We prepared a clean, structured file from your documents. "
        "The photos and scans you uploaded have been **deleted**; only the extracted details are kept."
    )

    user_pkg = repo.export_package(app.app_id, "user")
    st.download_button("Download my summary (PAN masked)", json.dumps(user_pkg, indent=2),
                       file_name=f"application_{app.app_id[:8]}_summary.json", mime="application/json")
    with st.expander("What is in the saved file?"):
        st.json(user_pkg)
    handoff_block(app)
    with st.expander("Audit trail"):
        st.dataframe(repo.audit_trail(app.app_id), use_container_width=True)

    if st.button("See my loan offers", type="primary"):
        go_to("extra_inputs")
