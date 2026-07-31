"""Benchmark evaluator — measures recommendation retrieval quality.

Runs 25 operational problems through the retrieval pipeline and computes
precision, recall, evidence mix, org diversity, and implementation depth.
"""

import sys
import os
from collections import Counter
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compass_collector.analysis.benchmark import get_all_problems
from compass_collector.analysis.retrieval import ImplementationQuery, find_comparable_implementations
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord


def normalize_cat(cat: str) -> str:
    cat = cat.lower().strip()
    aliases = {
        "workflow_automation": ["workflow_automation", "rpa", "workflow", "automation", "process_automation"],
        "ai": ["ai", "machine_learning", "artificial_intelligence", "genai", "generative_ai", "llm", "copilot"],
        "process_redesign": ["process_redesign", "process_improvement", "lean", "six_sigma"],
        "software": ["software", "saas", "platform", "erp", "crm", "cloud_migration"],
        "staffing": ["staffing", "hiring", "outsourcing"],
        "hybrid": ["hybrid"],
    }
    for std, al in aliases.items():
        if cat in al:
            return std
    return cat


def _get_impl_record(item: dict) -> InterventionRecord | None:
    """Look up the full InterventionRecord from its id."""
    rid = item.get("id")
    if not rid:
        return None
    s = get_session()
    try:
        return s.query(InterventionRecord).filter(InterventionRecord.id == rid).first()
    finally:
        s.close()


def _compute_impl_detail(item: dict, rec: InterventionRecord | None) -> float:
    """Compute implementation detail score from result item + record."""
    if rec and rec.implementation_detail_score:
        return rec.implementation_detail_score / 10.0
    if rec:
        fields = ["implementation_partner", "implementation_pattern", "lessons_learned",
                  "change_management", "rollout_strategy", "governance_model"]
        filled = sum(1 for f in fields if bool(getattr(rec, f, None)))
        if filled >= 2:
            return 0.5
        if filled >= 1:
            return 0.3
    lessons = item.get("lessons", [])
    if lessons:
        return 0.2
    return 0.0


@dataclass
class BResult:
    problem_id: str = ""
    query: str = ""
    retrieved: int = 0
    top5_relevant: int = 0
    top10_relevant: int = 0
    orgs_top10: int = 0
    gold: int = 0
    silver: int = 0
    bronze: int = 0
    has_negative: bool = False
    impl_records: int = 0
    avg_depth: float = 0.0
    precision_top5: float = 0.0
    precision_top10: float = 0.0
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def evaluate(problem: dict) -> BResult:
    r = BResult(problem_id=problem["id"], query=problem["query"])
    try:
        q = ImplementationQuery(
            workflow=problem["query"][:300],
            business_function=problem.get("business_function", ""),
        )
        result = find_comparable_implementations(q)
        items = result.get("results", [])[:10]
        r.retrieved = len(result.get("results", []))
        r.has_negative = result.get("negative_evidence_count", 0) > 0

        expected_cats = {normalize_cat(c) for c in problem.get("categories", [])}
        orgs = set()
        depths = []

        for i, item in enumerate(items):
            families = item.get("intervention_families", [])
            item_cats = {normalize_cat(f) for f in families}
            relevant = bool(item_cats & expected_cats)

            if relevant:
                if i < 5:
                    r.top5_relevant += 1
                r.top10_relevant += 1

            org = item.get("organization", "")
            if org:
                orgs.add(org)

            rec = _get_impl_record(item)
            if rec and rec.review_status:
                status = rec.review_status
                if status == "gold":
                    r.gold += 1
                elif status == "silver":
                    r.silver += 1
                else:
                    r.bronze += 1
            else:
                r.bronze += 1

            depth = _compute_impl_detail(item, rec)
            depths.append(depth)
            if depth > 0.3:
                r.impl_records += 1

        r.orgs_top10 = len(orgs)
        r.precision_top5 = r.top5_relevant / min(5, max(1, len(items)))
        r.precision_top10 = r.top10_relevant / max(1, len(items))
        r.avg_depth = sum(depths) / max(1, len(depths))

        if r.retrieved < problem.get("min_evidence", 3):
            r.warnings.append(f"retrieval {r.retrieved} < min {problem['min_evidence']}")
        if r.gold < problem.get("min_gold", 0):
            r.warnings.append(f"gold {r.gold} < min {problem['min_gold']}")
        if r.silver < problem.get("min_silver", 0):
            r.warnings.append(f"silver {r.silver} < min {problem['min_silver']}")
        if r.orgs_top10 < problem.get("min_orgs", 1):
            r.warnings.append(f"orgs {r.orgs_top10} < min {problem['min_orgs']}")
        if problem.get("expect_negative") and not r.has_negative:
            r.warnings.append("negative evidence missing")
        if r.retrieved == 0:
            r.failures.append("no results")
    except Exception as e:
        r.failures.append(str(e)[:200])
    return r


def run(problems=None):
    if problems is None:
        problems = get_all_problems()
    results = [evaluate(p) for p in problems]
    stats = _aggregate(results)
    return results, stats


def _aggregate(results: list[BResult]) -> dict:
    n = len(results)
    if n == 0:
        return {}
    return {
        "problems": n,
        "passed": sum(1 for r in results if not r.failures),
        "warnings": sum(len(r.warnings) for r in results),
        "failures": sum(len(r.failures) for r in results),
        "avg_retrieved": round(sum(r.retrieved for r in results) / n, 1),
        "avg_precision_top5": round(sum(r.precision_top5 for r in results) / n, 3),
        "avg_precision_top10": round(sum(r.precision_top10 for r in results) / n, 3),
        "avg_orgs": round(sum(r.orgs_top10 for r in results) / n, 1),
        "avg_depth": round(sum(r.avg_depth for r in results) / n, 3),
        "avg_impl_records": round(sum(r.impl_records for r in results) / n, 1),
        "gold": sum(r.gold for r in results),
        "silver": sum(r.silver for r in results),
        "bronze": sum(r.bronze for r in results),
        "neg_coverage": round(sum(1 for r in results if r.has_negative) / n, 3),
    }


def report(results: list[BResult], stats: dict):
    print("=" * 85)
    print("RECOMMENDATION RETRIEVAL BENCHMARK")
    print("=" * 85)
    print(f"Problems {stats['problems']}  Passed {stats['passed']}  Warnings {stats['warnings']}  Failures {stats['failures']}")
    print()
    hdr = f"{'Problem':<28} {'Retr':>4} {'P@5':>5} {'Orgs':>4} {'G':>3} {'S':>3} {'B':>3} {'Neg':>3} {'Impl':>4} {'Depth':>5} {'Status'}"
    print(hdr)
    print("-" * 85)
    for r in results:
        st = "FAIL" if r.failures else ("WARN" if r.warnings else "OK")
        print(f"{r.problem_id:<28} {r.retrieved:>4} {r.precision_top5:>5.2f} {r.orgs_top10:>4} {r.gold:>3} {r.silver:>3} {r.bronze:>3} {str(r.has_negative):>3} {r.impl_records:>4} {r.avg_depth:>5.2f} {st}")
        for w in r.warnings:
            print(f"  ! {w}")
    print()
    print("AGGREGATE")
    print("-" * 40)
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Key observations
    print()
    print("OBSERVATIONS")
    print("-" * 40)
    gold_total = stats["gold"]
    silver_total = stats["silver"]
    bronze_total = stats["bronze"]
    print(f"  Evidence mix: {gold_total} G / {silver_total} S / {bronze_total} B")
    print(f"  Silver-to-bronze ratio: {silver_total}/{bronze_total} = {silver_total/max(1,bronze_total):.2f}")
    if stats["avg_precision_top5"] < 0.3:
        print(f"  LOW precision (P@5={stats['avg_precision_top5']:.2f}) — retrieval relevance needs improvement")
    if stats["avg_impl_records"] < 2:
        print(f"  LOW implementation depth ({stats['avg_impl_records']} records/top10) — implementation fields underpopulated")
    if stats["neg_coverage"] < 0.3:
        print(f"  LOW negative evidence coverage ({stats['neg_coverage']:.0%}) — risk evidence underrepresented")
    if stats["avg_orgs"] < 3:
        print(f"  LOW org diversity ({stats['avg_orgs']} orgs/top10) — results too narrow")


if __name__ == "__main__":
    print("Running benchmark against live evidence graph...\n")
    results, stats = run()
    report(results, stats)
