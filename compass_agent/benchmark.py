"""Gold-set benchmarking for the enrichment pipeline.

Evaluates the LLM enrichment against a small fixed set of source passages with
known fields, reporting field-level precision/recall/F1. Results are persisted
to the agent store for trend tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from compass_agent.validate import validate_enrichment

log = logging.getLogger("compass_agent.benchmark")

# Fixed gold set: source text → expected field values. Deterministic and small
# enough to run in CI (each case is one LLM call when a key is configured).
GOLD_SET: list[dict] = [
    {
        "id": "shopify_migration",
        "text": (
            "Shopify migrated its data centers to Google Cloud beginning in 2016. "
            "During Black Friday weekend Shopify processed a record $14.6B in sales "
            "on Google Cloud, handling 489M peak requests per minute. The migration "
            "improved reliability at peak demand and reduced infrastructure cost."
        ),
        "expected": {
            "organization_name": "Shopify",
            "intervention_category": "Software",
            "evidence_tier": "gold",
            "workflow": "commerce processing",
        },
    },
    {
        "id": "support_chatbot",
        "text": (
            "A regional bank deployed a generative AI customer support chatbot with "
            "human review for complex cases across 120 agents. Average resolution time "
            "fell from 24 hours to 14.4 hours (40% improvement) and CSAT rose from 72 "
            "to 88 over a six-month pilot."
        ),
        "expected": {
            "organization_name": "bank",
            "intervention_category": "AI",
            "workflow": "customer support",
        },
    },
]


def _match_value(expected, actual) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    if isinstance(expected, str):
        e = expected.strip().lower()
        a = str(actual).strip().lower()
        return e == a or e in a or a in e
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return False
    if isinstance(expected, (list, set, tuple)):
        ea = {str(x).strip().lower() for x in expected}
        aa = {str(x).strip().lower() for x in actual} if isinstance(actual, list) else {str(actual).lower()}
        return bool(ea & aa)
    return False


@dataclass
class BenchmarkReport:
    run_id: str
    kind: str
    sample_size: int
    precision: float
    recall: float
    f1: float
    valid: int
    invalid: int
    per_case: dict
    per_field: dict

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "sample_size": self.sample_size,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "valid": self.valid,
            "invalid": self.invalid,
            "per_case": self.per_case,
            "per_field": self.per_field,
        }


def run_benchmark(
    enrich_fn: Callable[[str, str], dict],
    gold_set: Optional[list[dict]] = None,
    store: Optional[object] = None,
    kind: str = "enrichment",
    run_id: str = "",
) -> dict:
    """Run a gold-set benchmark.

    ``enrich_fn(text, title) -> payload dict``. In tests, pass a deterministic
    reference extractor instead of the live LLM.
    """
    from compass_agent.store import AgentStore

    gold_set = gold_set if gold_set is not None else GOLD_SET
    store = store or AgentStore()
    run_id = run_id or str(hash(tuple(g["id"] for g in gold_set)))

    per_case = {}
    field_totals: dict[str, dict] = {}
    matched_total = 0
    predicted_total = 0
    expected_total = 0
    valid_count = 0
    invalid_count = 0

    for case in gold_set:
        payload = enrich_fn(case["text"], case["id"])
        expected = case["expected"]
        report = validate_enrichment(payload)
        case_matched = 0
        case_predicted = 0
        case_expected = len(expected)
        expected_total += case_expected

        for field, exp in expected.items():
            field_totals.setdefault(field, {"expected": 0, "matched": 0, "predicted": 0})
            field_totals[field]["expected"] += 1
            actual = payload.get(field)
            if actual not in (None, "", [], {}):
                field_totals[field]["predicted"] += 1
                case_predicted += 1
            if _match_value(exp, actual):
                field_totals[field]["matched"] += 1
                case_matched += 1

        matched_total += case_matched
        predicted_total += case_predicted
        if report.valid:
            valid_count += 1
        else:
            invalid_count += 1
        per_case[case["id"]] = {
            "matched": case_matched,
            "expected": case_expected,
            "predicted": case_predicted,
            "valid": report.valid,
        }

    precision = (matched_total / predicted_total) if predicted_total else 1.0
    recall = (matched_total / expected_total) if expected_total else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    report_obj = BenchmarkReport(
        run_id=run_id,
        kind=kind,
        sample_size=len(gold_set),
        precision=precision,
        recall=recall,
        f1=f1,
        valid=valid_count,
        invalid=invalid_count,
        per_case=per_case,
        per_field={k: v for k, v in field_totals.items()},
    )
    stored_id = store.save_benchmark(kind, report_obj.to_dict())
    report_obj.run_id = stored_id
    return report_obj.to_dict()


def print_benchmark_report(report: dict) -> None:
    print("Compass Evidence Agent — Enrichment Benchmark")
    print(f"Run: {report['run_id']}  Kind: {report['kind']}  Sample: {report['sample_size']}")
    print(f"Precision: {report['precision']:.3f}  Recall: {report['recall']:.3f}  F1: {report['f1']:.3f}")
    print(f"Valid: {report['valid']}  Invalid: {report['invalid']}")
    for case_id, c in report["per_case"].items():
        print(f"  {case_id}: matched {c['matched']}/{c['expected']}, predicted {c['predicted']}, valid={c['valid']}")
