"""Process-wide singletons (database, file store). Kept out of core/ so core stays Streamlit-free."""
import streamlit as st

from core.db.repo import Repo
from core.storage import FileStore

RETENTION_HOURS = 24      # abandoned uploads are purged after this long


@st.cache_resource
def get_store() -> FileStore:
    store = FileStore()
    store.purge_older_than(RETENTION_HOURS)
    return store


@st.cache_resource
def get_repo() -> Repo:
    return Repo(store=get_store())


def persist(app) -> None:
    """Checkpoint the application. After a save, only status and audit events are written."""
    get_repo().sync(app)
