import hashlib
import shelve
import time
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, cache_dir: Path, ttl_seconds: int = 86400) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = str(cache_dir / "cache.db")
        self._ttl = ttl_seconds

    def _key(self, raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, raw_key: str) -> Any | None:
        k = self._key(raw_key)
        try:
            with shelve.open(self._path, flag="r") as db:
                if k not in db:
                    return None
                entry = db[k]
        except Exception:
            return None
        if self._ttl and (time.time() - entry["ts"]) > self._ttl:
            return None
        return entry["value"]

    def set(self, raw_key: str, value: Any) -> None:
        k = self._key(raw_key)
        with shelve.open(self._path) as db:
            db[k] = {"ts": time.time(), "value": value}

    def has(self, raw_key: str) -> bool:
        return self.get(raw_key) is not None
