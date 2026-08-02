"""Collector database bootstrap for the enrichment pipeline.

The agent needs the Compass collector database (130 MB) to find candidates to
enrich. The DB is excluded from the Railway build (see ``.railwayignore``) and
shipped in git as a git-lfs pointer, so the agent downloads a real copy at
startup — the same strategy the engine uses — and verifies it is a valid SQLite
database before activating enrichment.

Persistence: the download target defaults to ``<cwd>/data/collector_v3.db`` and
is cached in-process. Set ``AGENT_CANDIDATE_DB`` to a stable path (e.g. a
Railway volume) to avoid re-downloading on every restart.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger("compass_agent.db")

# Mirrors the engine's startup download URLs (main branch).
DEFAULT_DB_URLS = [
    "https://media.githubusercontent.com/media/smithar106/Compass-Engine/main/data/collector_v3.db",
    "https://raw.githubusercontent.com/smithar106/Compass-Engine/main/data/collector_v3.db",
]

# A real collector DB is ~130 MB; git-lfs pointer files are ~130 bytes. Anything
# below this is treated as a pointer/placeholder and re-downloaded.
MIN_REAL_DB_BYTES = 1024 * 1024  # 1 MB

_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def is_sqlite_db(path: str, min_size: int = MIN_REAL_DB_BYTES) -> bool:
    """True if ``path`` is a plausible real collector SQLite database."""
    if not path:
        return False
    try:
        size = os.path.getsize(path)
        if size < min_size:
            return False
        with open(path, "rb") as fh:
            magic = fh.read(16)
        if not magic.startswith(b"SQLite format 3\x00"):
            return False
        # Confirm the expected table exists.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='intervention_records'"
            ).fetchone()
            return bool(row and row[0] == 1)
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return False


def _download(path: str, urls: list[str], timeout: float = 120.0, min_size: int = MIN_REAL_DB_BYTES) -> bool:
    """Download the collector DB to ``path``. Returns success."""
    tmp = f"{path}.download"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        for url in urls:
            try:
                log.info("Downloading collector DB from %s", url)
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    with open(tmp, "wb") as out:
                        while True:
                            chunk = resp.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
                if is_sqlite_db(tmp, min_size=min_size):
                    os.replace(tmp, path)
                    log.info("Collector DB ready at %s (%.1f MB)", path, os.path.getsize(path) / 1e6)
                    return True
                log.warning("Downloaded file is not a valid collector DB (%s)", url)
                os.remove(tmp)
            except Exception as exc:
                log.warning("Download failed from %s: %s", url, exc)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return False
    except Exception as exc:
        log.error("Collector DB download error: %s", exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def ensure_collector_db(
    path: str = "",
    urls: list[str] | None = None,
    timeout: float = 120.0,
    allow_download: bool = True,
    min_size: int = MIN_REAL_DB_BYTES,
) -> str:
    """Resolve a valid collector DB path, downloading it if needed.

    Returns the validated path, or ``""`` when no valid DB could be obtained
    (the enrichment pipeline then stays inactive and the worker remains a
    connectivity/budget daemon).
    """
    target = path or os.path.join(os.getcwd(), "data", "collector_v3.db")
    urls = urls or DEFAULT_DB_URLS

    with _cache_lock:
        if target in _cache:
            return _cache[target]

        if is_sqlite_db(target, min_size=min_size):
            _cache[target] = target
            return target

        if not allow_download:
            _cache[target] = ""
            return ""

        if _download(target, urls, timeout, min_size) and is_sqlite_db(target, min_size=min_size):
            _cache[target] = target
            return target

        _cache[target] = ""
        return ""
