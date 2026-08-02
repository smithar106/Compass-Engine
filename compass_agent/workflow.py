"""Budget-controlled enrichment cycle.

``EnrichmentWorkflow.run_cycle`` ties together: claim candidates → enrich via
LLM (budget-gated) → validate → persist results → (optionally) auto-publish to
the collector DB. Enforces daily/total budget and the per-cycle document cap.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from compass_agent.claim import ClaimQueue
from compass_agent.daemon import BudgetTracker
from compass_agent.enrich import EnrichmentPipeline, EnrichmentOutcome
from compass_agent.publish import Publisher
from compass_agent.store import AgentStore

log = logging.getLogger("compass_agent.workflow")


@dataclass
class CycleReport:
    cycle: int
    candidates: int = 0
    processed: int = 0
    valid: int = 0
    invalid: int = 0
    skipped: int = 0
    published: int = 0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "candidates": self.candidates,
            "processed": self.processed,
            "valid": self.valid,
            "invalid": self.invalid,
            "skipped": self.skipped,
            "published": self.published,
            "cost": round(self.cost, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class EnrichmentWorkflow:
    def __init__(
        self,
        queue: ClaimQueue,
        pipeline: EnrichmentPipeline,
        store: AgentStore,
        budget: BudgetTracker,
        publisher: Optional[Publisher] = None,
        concurrency: int = 2,
        auto_publish: bool = False,
        model: str = "",
    ) -> None:
        self.queue = queue
        self.pipeline = pipeline
        self.store = store
        self.budget = budget
        self.publisher = publisher or Publisher()
        self.concurrency = max(1, concurrency)
        self.auto_publish = auto_publish
        self.model = model or pipeline.llm.model

    def _budget_gate(self) -> bool:
        return self.budget.can_work()

    def run_cycle(self, cycle: int, max_docs: int) -> CycleReport:
        report = CycleReport(cycle=cycle)
        if not self.budget.can_work():
            report.failures.append("budget exhausted — cycle skipped")
            log.warning("Enrichment cycle skipped: budget exhausted.")
            return report

        candidates = self.queue.next_batch(max_docs)
        report.candidates = len(candidates)
        if not candidates:
            log.info("No enrichment candidates in cycle %d.", cycle)
            return report

        # Batch-level budget pre-check: estimate the whole batch.
        estimated = sum(self.pipeline.llm.estimate_cost(c.get("text", "")) for c in candidates)
        remaining = min(
            self.budget.max_daily - self.budget.daily_spent,
            self.budget.max_total - self.budget.total_spent,
        )
        budget_for_batch = max(0.0, remaining)
        if budget_for_batch <= 0:
            report.failures.append("insufficient budget for any candidate")
            for c in candidates:
                self.queue.complete(c["id"], status="skipped")
            return report

        outcomes: list[EnrichmentOutcome] = []
        if self.concurrency > 1 and len(candidates) > 1:
            with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
                futures = [
                    ex.submit(
                        self.pipeline.enrich_candidate,
                        c,
                        budget_gate=self._budget_gate,
                    )
                    for c in candidates
                ]
                for f in futures:
                    try:
                        outcomes.append(f.result())
                    except Exception as exc:  # worker crashed — mark failed
                        report.failures.append(f"worker error: {exc}")
        else:
            for c in candidates:
                outcomes.append(
                    self.pipeline.enrich_candidate(c, budget_gate=self._budget_gate)
                )

        for outcome in outcomes:
            self._settle_outcome(report, outcome)
        return report

    def _settle_outcome(self, report: CycleReport, outcome: EnrichmentOutcome) -> None:
        report.processed += 1
        report.cost += outcome.cost
        report.input_tokens += outcome.input_tokens
        report.output_tokens += outcome.output_tokens

        if outcome.skipped:
            report.skipped += 1
            self.queue.complete(outcome.candidate_id, status="skipped")
            return

        self.store.save_result(
            candidate_id=outcome.candidate_id,
            record_id=outcome.record_id,
            payload=outcome.payload,
            validation=outcome.report.to_dict(),
            valid=outcome.valid,
            cost=outcome.cost,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            model=outcome.model,
        )

        # Spend actual cost AFTER the work happened, but never allow the ledger
        # to exceed the ceilings.
        if outcome.cost > 0:
            self.budget.spend(outcome.cost)

        if outcome.valid:
            report.valid += 1
            if self.auto_publish and outcome.record_id:
                report.published += self.publisher.publish(
                    outcome.record_id, outcome.payload
                )
            self.queue.complete(outcome.candidate_id, status="done")
        else:
            report.invalid += 1
            self.queue.complete(outcome.candidate_id, status="failed")
