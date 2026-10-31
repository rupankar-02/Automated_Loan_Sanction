"""KYC provider interface. Real Aadhaar eKYC / CKYC / DigiLocker / video-KYC need regulated partners;
the demo implements this interface with a mock."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ReadinessItem:
    label: str
    ok: bool
    note: str = ""


@dataclass
class KYCSession:
    session_id: str
    method: str
    status: str = "started"               # started | otp_verified | completed | failed
    steps_done: list[str] = field(default_factory=list)
    demo: bool = True


class KYCProvider(Protocol):
    def readiness(self, state) -> list[ReadinessItem]: ...
    def start(self, application_id: str) -> KYCSession: ...
    def verify_otp(self, session: KYCSession, code: str) -> bool: ...
    def complete(self, session: KYCSession, selfie_captured: bool) -> KYCSession: ...
