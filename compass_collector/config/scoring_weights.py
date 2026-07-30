from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Dict


SCORING_MODEL_VERSION = "1.0.0"


DEFAULT_SCORING_WEIGHTS: Dict[str, float] = {
    "problem_alignment": 0.30,
    "organizational_similarity": 0.20,
    "goal_alignment": 0.20,
    "evidence_strength": 0.15,
    "implementation_fit": 0.10,
    "outcome_consistency": 0.05,
}


class ScoringConfig(BaseModel):
    version: str = SCORING_MODEL_VERSION
    weights: Dict[str, float] = DEFAULT_SCORING_WEIGHTS
    created_at: str = ""


def get_scoring_config() -> ScoringConfig:
    return ScoringConfig(
        version=SCORING_MODEL_VERSION,
        weights=dict(DEFAULT_SCORING_WEIGHTS),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def validate_weights(weights: Dict[str, float]) -> Dict[str, float]:
    expected_keys = set(DEFAULT_SCORING_WEIGHTS.keys())
    given_keys = set(weights.keys())
    if not expected_keys.issubset(given_keys):
        missing = expected_keys - given_keys
        raise ValueError(f"Missing weight keys: {missing}")
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        raise ValueError(f"Weights must sum to 1.0, got {total}")
    return {k: weights[k] for k in expected_keys}
