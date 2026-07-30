"""Recommendation result persistence.

Stores completed recommendation responses as JSON files keyed by
recommendation_id in the data directory. This enables PDF generation
and result retrieval without re-running the engine.
"""

import json
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from compass_collector.config.settings import DATA_DIR
from compass_collector.api.schemas import RecommendationResponse, InterventionSelectionResponse

logger = logging.getLogger("compass-engine.storage")

RECOMMENDATIONS_DIR = DATA_DIR / "recommendations"
SELECTIONS_DIR = DATA_DIR / "selections"

SCORING_MODEL_VERSION = "1.0.0"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_recommendation(response: RecommendationResponse) -> str:
    _ensure_dir(RECOMMENDATIONS_DIR)
    rec_id = response.recommendation_id
    if not rec_id:
        rec_id = str(uuid.uuid4())
    filepath = RECOMMENDATIONS_DIR / f"{rec_id}.json"
    data = response.model_dump()
    data["_schema_version"] = SCORING_MODEL_VERSION
    data["_stored_at"] = datetime.now(timezone.utc).isoformat()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved recommendation {rec_id} to {filepath}")
    return rec_id


def load_recommendation(rec_id: str) -> Optional[dict]:
    _ensure_dir(RECOMMENDATIONS_DIR)
    filepath = RECOMMENDATIONS_DIR / f"{rec_id}.json"
    if not filepath.exists():
        logger.warning(f"Recommendation {rec_id} not found at {filepath}")
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load recommendation {rec_id}: {e}")
        return None


def recommendation_exists(rec_id: str) -> bool:
    _ensure_dir(RECOMMENDATIONS_DIR)
    return (RECOMMENDATIONS_DIR / f"{rec_id}.json").exists()


def save_selection(selection: InterventionSelectionResponse) -> str:
    _ensure_dir(SELECTIONS_DIR)
    sel_id = selection.selection_id
    if not sel_id:
        sel_id = str(uuid.uuid4())
    filepath = SELECTIONS_DIR / f"{sel_id}.json"
    data = selection.model_dump()
    data["_schema_version"] = SCORING_MODEL_VERSION
    data["_stored_at"] = datetime.now(timezone.utc).isoformat()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved selection {sel_id} to {filepath}")
    return sel_id


def load_selection(sel_id: str) -> Optional[dict]:
    _ensure_dir(SELECTIONS_DIR)
    filepath = SELECTIONS_DIR / f"{sel_id}.json"
    if not filepath.exists():
        logger.warning(f"Selection {sel_id} not found at {filepath}")
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load selection {sel_id}: {e}")
        return None


def load_selection_by_recommendation(rec_id: str) -> Optional[dict]:
    _ensure_dir(SELECTIONS_DIR)
    for fpath in SELECTIONS_DIR.glob("*.json"):
        try:
            with open(fpath) as f:
                data = json.load(f)
            if data.get("recommendation_id") == rec_id:
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


def save_score_breakdown(rec_id: str, breakdown: dict):
    _ensure_dir(RECOMMENDATIONS_DIR)
    filepath = RECOMMENDATIONS_DIR / f"{rec_id}_breakdown.json"
    data = {
        "recommendation_id": rec_id,
        "breakdown": breakdown,
        "_stored_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def load_score_breakdown(rec_id: str) -> Optional[dict]:
    _ensure_dir(RECOMMENDATIONS_DIR)
    filepath = RECOMMENDATIONS_DIR / f"{rec_id}_breakdown.json"
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
