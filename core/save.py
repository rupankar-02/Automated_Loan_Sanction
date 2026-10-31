"""Confirm and save: persist, purge the original files, and scrub sensitive values from memory."""
from core.db.repo import Repo
from core.state import ApplicationState, readiness
from core.utils.pii import SENSITIVE_KEYS, scrub_state_value


class NotReady(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def scrub_state(state: ApplicationState) -> None:
    for slot in state.slots.values():
        for part in slot.parts:
            for f in part.fields:
                if f.key in SENSITIVE_KEYS:
                    f.raw_value = scrub_state_value(f.key, f.raw_value)
                    f.normalized_value = scrub_state_value(f.key, f.normalized_value)
    state.scrubbed = True


def confirm_and_save(state: ApplicationState, repo: Repo) -> dict:
    ok, problems = readiness(state)
    if not ok:
        raise NotReady(problems)
    state.log("confirmed")
    repo.sync(state, status="saved")                  # protect_value runs on every field here
    purged = repo.store.purge(state.app_id)           # originals hold the full Aadhaar/account numbers
    repo.clear_storage_paths(state.app_id)
    scrub_state(state)
    state.log("files_purged", count=purged)
    state.log("saved")
    repo.sync(state)                                  # scrubbed: only status and audit events are written
    return repo.export_package(state.app_id, "user")
