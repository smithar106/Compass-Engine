"""Demand telemetry — measured evidence demand from real user queries.

Phase 5 of the Evidence Gap Engine. Every Analyze/Outcome request records the
workflow it concerns (inferred from the problem/intervention text, canonical
via ``workflow_taxonomy``). The gap engine then weights categories by
*measured* demand instead of the curated keyword table.

Storage: a small JSON counter at ``data/telemetry/demand.json`` (raw counts,
thread-safe via a module lock + atomic rename). Export normalizes counts to
0..1 for the gap engine's ``demand_override``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from compass_collector.config.settings import DATA_DIR

log = logging.getLogger("compass_collector.api.demand_telemetry")

DEMAND_FILE = Path(DATA_DIR) / "telemetry" / "demand.json"
_lock = threading.Lock()


def _load() -> dict[str, int]:
    try:
        if DEMAND_FILE.exists():
            data = json.loads(DEMAND_FILE.read_text())
            return {str(k): int(v) for k, v in data.items() if v}
    except Exception as exc:  # noqa: BLE001
        log.warning("demand telemetry read failed: %s", exc)
    return {}


def _save(counts: dict[str, int]) -> None:
    try:
        DEMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DEMAND_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(counts, indent=2, sort_keys=True))
        tmp.replace(DEMAND_FILE)
    except Exception as exc:  # noqa: BLE001
        log.warning("demand telemetry write failed: %s", exc)


def record_demand_from_text(text: Optional[str], weight: float = 1.0) -> Optional[str]:
    """Increment demand for the canonical workflow a request concerns.

    Returns the canonical workflow slug recorded, or None when the text
    carries no workflow signal.
    """
    if not text or not str(text).strip():
        return None
    from compass_collector.organization.workflow_taxonomy import infer_workflow

    nv = infer_workflow(str(text)[:2000])
    if not nv.value or nv.value in ("uncategorized",) or nv.confidence < 0.5:
        return None
    slug = nv.value
    with _lock:
        counts = _load()
        counts[slug] = counts.get(slug, 0) + max(0.0, float(weight))
        _save(counts)
    return slug


def load_demand_for_engine() -> dict[str, float]:
    """Normalized workflow-slug → demand weight (0..1) for the gap engine."""
    counts = _load()
    if not counts:
        return {}
    top = max(counts.values())
    if top <= 0:
        return {}
    return {slug: round(count / top, 3) for slug, count in counts.items()}


def demand_summary() -> dict:
    counts = _load()
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return {
        "file": str(DEMAND_FILE),
        "total": sum(counts.values()),
        "distinct_workflows": len(counts),
        "top": [{"workflow": w, "count": c} for w, c in ranked[:20]],
    }


__all__ = ["record_demand_from_text", "load_demand_for_engine", "demand_summary", "DEMAND_FILE"]
