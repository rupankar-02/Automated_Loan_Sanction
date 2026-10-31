"""Mock KYC. Everything here is a demo: any 6-digit OTP passes and no face match is performed."""
import re
import uuid

from rapidfuzz import fuzz

from core.kyc.base import KYCSession, ReadinessItem
from core.models import FieldStatus
from core.state import ApplicationState

_OK = {FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID}


def _field(state: ApplicationState, slot_id: str, key: str):
    slot = state.slots.get(slot_id)
    return next((f for p in (slot.parts if slot else []) for f in p.fields if f.key == key), None)


class MockKYCProvider:
    method = "mock_aadhaar_otp_selfie"

    def readiness(self, state: ApplicationState) -> list[ReadinessItem]:
        """What is already verified from the documents. Uses validation statuses, never raw numbers."""
        pan, aad = _field(state, "pan", "pan_number"), _field(state, "aadhaar_front", "aadhaar_number")
        items = [
            ReadinessItem("PAN format is valid", bool(pan and pan.status in _OK)),
            ReadinessItem("Aadhaar number passes the check-digit test", bool(aad and aad.status in _OK),
                          "The number itself is stored masked."),
        ]
        n1, n2 = _field(state, "pan", "name"), _field(state, "aadhaar_front", "name")
        if n1 and n2 and n1.normalized_value and n2.normalized_value:
            score = fuzz.token_sort_ratio(n1.normalized_value.upper(), n2.normalized_value.upper())
            items.append(ReadinessItem("Name matches between PAN and Aadhaar", score >= 85, f"similarity {score:.0f}%"))
        d1, d2 = _field(state, "pan", "dob"), _field(state, "aadhaar_front", "dob")
        if d1 and d2 and d1.normalized_value and d2.normalized_value:
            items.append(ReadinessItem("Date of birth matches between PAN and Aadhaar", d1.normalized_value == d2.normalized_value))
        return items

    def start(self, application_id: str) -> KYCSession:
        return KYCSession(session_id=uuid.uuid4().hex, method=self.method)

    def verify_otp(self, session: KYCSession, code: str) -> bool:
        ok = bool(re.fullmatch(r"\d{6}", code.strip()))
        if ok:
            session.status = "otp_verified"
            session.steps_done.append("otp")
        return ok

    def complete(self, session: KYCSession, selfie_captured: bool) -> KYCSession:
        if session.status != "otp_verified" or not selfie_captured:
            session.status = "failed"
            return session
        session.steps_done += ["selfie", "face_match_mocked"]   # the selfie image is never stored
        session.status = "completed"
        return session
