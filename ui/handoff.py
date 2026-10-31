"""Lender handoff package: a separate, explicit action. Contains the full PAN, so it is audited."""
import json

import streamlit as st

from ui.services import get_repo


def handoff_block(app) -> None:
    repo = get_repo()
    with st.expander("Lender handoff package (full PAN)"):
        st.warning("This package contains the full PAN and is meant for the lender only. Aadhaar and account numbers stay "
                   "masked. It includes the selected offer and the eligibility run behind it. Creating it is recorded in the audit trail.")
        if st.checkbox("I understand, create the lender package", key="lender_ok"):
            if st.button("Create lender package"):
                repo.log(app.app_id, "lender_package_exported")
                st.session_state["lender_pkg"] = json.dumps(repo.export_package(app.app_id, "lender"), indent=2)
            if pkg := st.session_state.get("lender_pkg"):
                st.download_button("Download lender package", pkg, file_name=f"application_{app.app_id[:8]}_lender.json",
                                   mime="application/json")
