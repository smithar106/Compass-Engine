"""Verified evidence — canonical, engine-managed source of verified records.

Serves the curated verified evidence set (source-verified records with an
explicit comparability classification and outcome-attribution status). This is
the single canonical source; the web must not maintain its own copy.

Endpoint:
  GET /api/evidence/verified?workflow=<canonical slug>

Response includes, per record: source metadata, supporting passages,
verification_status (source dimension), comparability + outcome_attribution
(relevance dimensions), and a fail-closed `supports_direct_outcome` flag.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from compass_collector.analysis.evidence_comparability import (
    parse_comparability,
    parse_attribution,
    supports_direct_outcome_claim,
    attribution_limitation,
)

router = APIRouter(prefix="/api/evidence", tags=["verified"])

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "verified"


def _load(workflow: str) -> dict | None:
    path = _DATA_DIR / f"{workflow}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


@router.get("/verified")
def verified_evidence(workflow: str = ""):
    """Return the verified evidence set for a workflow (canonical, engine-managed)."""
    wf = (workflow or "").strip().lower()
    if not wf:
        return JSONResponse({"error": "missing workflow parameter"}, status_code=400)

    data = _load(wf)
    if not data:
        return JSONResponse({"workflow": wf, "available": False, "records": [], "summary": {}}, status_code=200)

    records = []
    for r in data.get("records", []):
        comp = parse_comparability(r.get("comparability"))
        attr = parse_attribution(r.get("outcome_attribution"))
        records.append({
            "id": r.get("id"),
            "organization": r.get("organization"),
            "intervention": r.get("intervention"),
            "what_it_establishes": r.get("what_it_establishes"),
            "metrics": r.get("metrics", []),
            "source": r.get("source", {}),
            # pre -> intervention -> post flow (explicit)
            "flow": r.get("flow", {}),
            # source dimension
            "verification_status": r.get("verification_status", "legacy"),
            # relevance dimensions (independent)
            "comparability": comp.value,
            "outcome_attribution": attr.value,
            "comparability_reason": r.get("comparability_reason", ""),
            "selection_reason": r.get("selection_reason", ""),
            # fail-closed gate
            "supports_direct_outcome": supports_direct_outcome_claim(comp, attr),
            "attribution_limitation": attribution_limitation(comp, attr),
        })

    def _count(key: str, value: str) -> int:
        return sum(1 for r in records if r.get(key) == value)

    summary = {
        "total": len(records),
        "direct_implementation": _count("comparability", "direct_implementation"),
        "indirect_contextual": _count("comparability", "indirect_contextual"),
        "not_relevant": _count("comparability", "not_relevant"),
        "unassessed": _count("comparability", "unassessed"),
        "supports_direct_outcome": sum(1 for r in records if r["supports_direct_outcome"]),
    }

    return JSONResponse({
        "workflow": data.get("workflow", wf),
        "category": data.get("category", ""),
        "problem": data.get("problem", ""),
        "recommendation": data.get("recommendation", ""),
        "reviewed_at": data.get("reviewed_at", ""),
        "notes": data.get("notes", ""),
        "available": True,
        "records": records,
        "summary": summary,
    })
