"""Plan step: CampaignPlanner.

Ranks decision categories by expected impact (from gap analysis), estimates the
evidence needed, proposes high-value source types, and persists a Campaign that
tracks status, cost, and benchmark improvement after publication.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from compass_agent.gap_analysis import GapCategory
from compass_agent.store import AgentStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Campaign:
    workflow: str
    business_function: str
    target_fields: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    estimated_records_needed: int = 0
    expected_impact: float = 0.0
    # Gap Engine v2 (Phase 4): composed hunting directives. In-memory only —
    # used by the current discovery pass; not persisted in the store.
    search_terms: list[str] = field(default_factory=list)
    library_priority: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "planned"  # planned | active | completed | archived
    discovered: int = 0
    accepted: int = 0
    rejected: int = 0
    rich_records_created: int = 0
    cost_usd: float = 0.0
    benchmark_before: float = 0.0
    benchmark_after: Optional[float] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow": self.workflow,
            "business_function": self.business_function,
            "status": self.status,
            "target_fields": self.target_fields,
            "source_types": self.source_types,
            "estimated_records_needed": self.estimated_records_needed,
            "expected_impact": round(self.expected_impact, 3),
            "discovered": self.discovered,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rich_records_created": self.rich_records_created,
            "cost_usd": round(self.cost_usd, 6),
            "benchmark_before": round(self.benchmark_before, 3),
            "benchmark_after": round(self.benchmark_after, 3) if self.benchmark_after is not None else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _benchmark_before(gap: GapCategory) -> float:
    """A category's current benchmark score (0..1) from its gap health."""
    return round(max(0.0, 1.0 - gap.gap_score), 3)


class CampaignPlanner:
    def __init__(self, store: AgentStore, min_impact: float = 0.1, top_n: int = 3) -> None:
        self.store = store
        self.min_impact = min_impact
        self.top_n = top_n

    def plan(self, gaps: list[GapCategory]) -> list[Campaign]:
        """Create + persist campaigns for the highest-impact categories."""
        eligible = [g for g in gaps if g.expected_impact >= self.min_impact][: self.top_n]
        campaigns = []
        for gap in eligible:
            campaign = Campaign(
                workflow=gap.workflow,
                business_function=gap.business_function,
                target_fields=gap.missing_fields,
                source_types=gap.proposed_source_types,
                estimated_records_needed=gap.estimated_records_needed,
                expected_impact=gap.expected_impact,
                benchmark_before=_benchmark_before(gap),
            )
            self.store.save_campaign(campaign.to_dict())
            campaigns.append(campaign)
        return campaigns

    def active_campaigns(self) -> list[dict]:
        return self.store.list_campaigns(status="active")
