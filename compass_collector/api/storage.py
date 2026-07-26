"""Recommendation result persistence.

Stores completed recommendation responses as JSON files keyed by
recommendation_id in the data directory. This enables PDF generation
and result retrieval without re-running the engine.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from compass_collector.config.settings import DATA_DIR
from compass_collector.api.schemas import RecommendationResponse

logger = logging.getLogger("compass-engine.storage")

RECOMMENDATIONS_DIR = DATA_DIR / "recommendations"


def _ensure_dir() -> Path:
    RECOMMENDATIONS_DIR.mkdir(parents=True, exist_ok=True)
    return RECOMMENDATIONS_DIR


def save_recommendation(response: RecommendationResponse) -> str:
    _ensure_dir()
    rec_id = response.recommendation_id
    if not rec_id:
        rec_id = str(int(datetime.now(timezone.utc).timestamp()))
    filepath = RECOMMENDATIONS_DIR / f"{rec_id}.json"
    data = response.model_dump()
    data["_schema_version"] = "3.0.0"
    data["_stored_at"] = datetime.now(timezone.utc).isoformat()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Saved recommendation {rec_id} to {filepath}")
    return rec_id


def load_recommendation(rec_id: str) -> Optional[dict]:
    _ensure_dir()
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
    _ensure_dir()
    return (RECOMMENDATIONS_DIR / f"{rec_id}.json").exists()
