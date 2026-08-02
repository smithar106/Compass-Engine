"""Enrichment pipeline: one candidate → one validated enrichment outcome."""

from __future__ import annotations

from dataclasses import dataclass

from compass_agent.llm import LLMClient
from compass_agent.validate import ValidationReport, validate_enrichment


@dataclass
class EnrichmentOutcome:
    candidate_id: str
    record_id: str
    payload: dict
    report: ValidationReport
    cost: float
    input_tokens: int
    output_tokens: int
    model: str
    skipped: bool = False
    skip_reason: str = ""

    @property
    def valid(self) -> bool:
        return self.report.valid and not self.skipped


class EnrichmentPipeline:
    """Runs one candidate through the LLM, returning a validated outcome."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def enrich_candidate(
        self,
        candidate: dict,
        budget_gate=None,
    ) -> EnrichmentOutcome:
        candidate_id = candidate["id"]
        text = candidate.get("text") or ""

        if not self.llm.can_run:
            return EnrichmentOutcome(
                candidate_id=candidate_id,
                record_id=candidate.get("record_id", ""),
                payload={},
                report=ValidationReport(valid=False, issues=["LLM client has no API key"]),
                cost=0.0, input_tokens=0, output_tokens=0, model=self.llm.model,
                skipped=True, skip_reason="no_api_key",
            )
        if budget_gate is not None and not budget_gate():
            return EnrichmentOutcome(
                candidate_id=candidate_id,
                record_id=candidate.get("record_id", ""),
                payload={},
                report=ValidationReport(valid=False, issues=["budget exhausted"]),
                cost=0.0, input_tokens=0, output_tokens=0, model=self.llm.model,
                skipped=True, skip_reason="budget",
            )

        result = self.llm.enrich(
            text, title=candidate.get("title", ""), url=candidate.get("source", "")
        )
        report = validate_enrichment(result.payload)
        return EnrichmentOutcome(
            candidate_id=candidate_id,
            record_id=candidate.get("record_id", ""),
            payload=result.payload,
            report=report,
            cost=result.cost,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            model=result.model,
        )
