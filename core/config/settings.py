import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(*names: str, default: str = "") -> str:
    """Case-insensitive lookup over several accepted variable names."""
    lowered = {k.strip().lower(): v.strip() for k, v in os.environ.items()}
    for n in names:
        if lowered.get(n.lower()):
            return lowered[n.lower()]
    return default


class Settings(BaseModel):
    hf_token: str = ""
    gemini_api_key: str = ""
    gemini_api_key2: str = ""          # second key: tried when the first is overloaded or rate-limited
    sarvam_api_key: str = ""
    hf_model_id: str = ""
    # Default model choice, "<provider>:<model>"; the UI can override per session.
    default_model: str = "gemini:gemini-3-flash-preview"
    # Used when the default model is overloaded (Gemini returns 503 "high demand" from time to time).
    fallback_model: str = "gemini:gemini-3.5-flash"
    use_mock_vlm: bool = False
    classifier: str = "local"          # "local" = OCR + keywords (no API); "gemini" = ask a vision model
    data_dir: Path = ROOT / "data"


_NAMES = ("HF_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY2", "SARVAM_API_KEY", "HF_MODEL_ID",
          "VLM_MODEL_ID", "VLM_DEFAULT_MODEL", "VLM_FALLBACK_MODEL", "USE_MOCK_VLM", "CLASSIFIER")
_cached: tuple[tuple[str, ...], Settings] | None = None


def get_settings() -> Settings:
    """The same object for as long as the environment is unchanged, rebuilt when a key is added or changed.

    A permanent cache broke hosted deploys: if the app started before its secrets were saved, it kept the
    empty values (and "SARVAM_API_KEY is not set") until a full restart.
    """
    global _cached
    snapshot = tuple(_env(n) for n in _NAMES)
    if _cached is None or _cached[0] != snapshot:
        _cached = (snapshot, _build())
    return _cached[1]


def _build() -> Settings:
    return Settings(
        hf_token=_env("HF_TOKEN"),
        gemini_api_key=_env("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        gemini_api_key2=_env("GEMINI_API_KEY2"),
        sarvam_api_key=_env("SARVAM_API_KEY"),
        hf_model_id=_env("HF_MODEL_ID", "VLM_MODEL_ID"),
        default_model=_env("VLM_DEFAULT_MODEL", default="gemini:gemini-3-flash-preview"),
        fallback_model=_env("VLM_FALLBACK_MODEL", default="gemini:gemini-3.5-flash"),
        use_mock_vlm=_env("USE_MOCK_VLM", default="0") == "1",
        classifier=_env("CLASSIFIER", default="local").lower(),
    )
