"""Temporary storage for uploaded originals. They contain full Aadhaar/account numbers, so they are
kept only until the user confirms, then purged; stale ones are purged by age."""
import shutil
import time
from pathlib import Path

from core.config.settings import get_settings


class FileStore:
    def __init__(self, base: Path | None = None):
        self.base = Path(base) if base else get_settings().data_dir / "uploads"

    def _dir(self, app_id: str) -> Path:
        return self.base / app_id

    def save(self, app_id: str, file_hash: str, data: bytes, suffix: str = "") -> Path:
        d = self._dir(app_id)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{file_hash}{suffix}"
        if not p.exists():
            p.write_bytes(data)
        return p

    def path_for(self, app_id: str, file_hash: str) -> Path | None:
        d = self._dir(app_id)
        if d.exists():
            for p in d.iterdir():
                if p.name.startswith(file_hash):
                    return p
        return None

    def purge(self, app_id: str) -> int:
        d = self._dir(app_id)
        n = len(list(d.iterdir())) if d.exists() else 0
        shutil.rmtree(d, ignore_errors=True)
        return n

    def purge_older_than(self, hours: float) -> int:
        removed = 0
        if self.base.exists():
            cutoff = time.time() - hours * 3600
            for d in self.base.iterdir():
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
        return removed

    def count(self, app_id: str) -> int:
        d = self._dir(app_id)
        return len(list(d.iterdir())) if d.exists() else 0
