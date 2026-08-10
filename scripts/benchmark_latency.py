"""Recommendation API latency benchmark.

Usage:
    python scripts/benchmark_latency.py [--trials N] [--p95-target 3.0]

Runs N recommendation requests against the engine, measures wall-clock
latency for each, and reports P50, P95, P99 and whether P95 meets target.

Target: P95 < 3 seconds (3000ms).
"""

import argparse
import statistics
import sys
import time
import json
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.api.service import run_recommendation
from compass_collector.api.schemas import InvestigationRequest

ASSESSMENT_SCENARIOS = [
    {
        "name": "finance_automation",
        "business_function": "finance",
        "workflow": "invoice_processing",
        "problem_statement": "Manual invoice processing",
        "constraint": "speed",
        "desired_outcome": "efficiency",
        "industry": "financial_services",
        "company_size": "medium",
        "budget_range": "$50k–100k",
        "implementation_timeline": "1–3 months",
        "exception_rate": "some (<10%)",
        "annual_workflow_volume": "12000",
        "current_handling_time": "0.25",
        "loaded_labor_cost": "45",
    },
    {
        "name": "support_routing",
        "business_function": "support",
        "workflow": "ticketing",
        "problem_statement": "Support ticket triage",
        "constraint": "errors",
        "desired_outcome": "quality",
        "industry": "technology",
        "company_size": "large",
        "budget_range": "$100k–250k",
        "implementation_timeline": "3–6 months",
        "exception_rate": "10–30%",
        "annual_workflow_volume": "50000",
        "current_handling_time": "0.15",
        "loaded_labor_cost": "55",
    },
    {
        "name": "hr_onboarding",
        "business_function": "human_resources",
        "workflow": "onboarding",
        "problem_statement": "Employee onboarding workflow",
        "constraint": "capacity",
        "desired_outcome": "time",
        "industry": "professional_services",
        "company_size": "small",
        "budget_range": "$25k–50k",
        "implementation_timeline": "30 days",
        "exception_rate": "almost no exceptions",
        "annual_workflow_volume": "600",
        "current_handling_time": "2.0",
        "loaded_labor_cost": "35",
    },
]


def run_one(scenario: dict) -> tuple[float, bool, str]:
    req = InvestigationRequest(**{
        k: v for k, v in scenario.items()
        if k not in ("name",)
    })
    start = time.perf_counter()
    try:
        result = run_recommendation(req)
        elapsed_ms = (time.perf_counter() - start) * 1000
        success = bool(result.recommendations)
        return elapsed_ms, success, ""
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return elapsed_ms, False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Compass recommendation latency benchmark")
    parser.add_argument("--trials", type=int, default=20, help="Total recommendation requests (default 20)")
    parser.add_argument("--p95-target", type=float, default=3.0, help="P95 target in seconds (default 3.0)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--cold-start", action="store_true", help="Include first request (cold gap engine)")
    args = parser.parse_args()

    latencies = []
    failures = 0
    errors = []

    # Warm the gap engine cache once so we measure the steady-state hot path
    if not args.cold_start:
        try:
            run_recommendation(InvestigationRequest(
                business_function="finance", workflow="invoice_processing",
                problem_statement="warmup", constraint="speed",
            ))
        except Exception:
            pass

    per_scenario = args.trials // len(ASSESSMENT_SCENARIOS) + 1

    for scenario in ASSESSMENT_SCENARIOS:
        for _ in range(per_scenario):
            if len(latencies) >= args.trials:
                break
            elapsed, ok, err = run_one(scenario)
            if not ok:
                failures += 1
                errors.append(f"{scenario['name']}: {err}")
            latencies.append(elapsed)

    if not latencies:
        print("ERROR: No measurements collected.", file=sys.stderr)
        sys.exit(1)

    latencies.sort()
    n = len(latencies)

    p50 = latencies[n // 2]
    p95_idx = int(n * 0.95)
    p95 = latencies[min(p95_idx, n - 1)]
    p99_idx = int(n * 0.99)
    p99 = latencies[min(p99_idx, n - 1)]
    mean = statistics.mean(latencies)
    stdev = statistics.stdev(latencies) if n > 1 else 0
    p95_seconds = p95 / 1000
    target = args.p95_target
    passed = p95_seconds <= target

    result = {
        "trials": n,
        "failures": failures,
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p95_seconds": round(p95_seconds, 2),
        "p95_target": target,
        "p95_pass": passed,
        "p99_ms": round(p99, 1),
        "mean_ms": round(mean, 1),
        "stdev_ms": round(stdev, 1),
        "min_ms": round(latencies[0], 1),
        "max_ms": round(latencies[-1], 1),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if passed else "FAIL"
        print(f"\n  P50: {p50:8.1f} ms")
        print(f"  P95: {p95:8.1f} ms  ({p95_seconds:.2f}s)  target ≤ {target}s  [{status}]")
        print(f"  P99: {p99:8.1f} ms")
        print(f" mean: {mean:8.1f} ms  σ={stdev:.1f}")
        print(f"  min: {latencies[0]:8.1f} ms")
        print(f"  max: {latencies[-1]:8.1f} ms")
        print(f"  n={n}  failures={failures}")

    if failures:
        print(f"\n  {failures} failure(s):", file=sys.stderr)
        for err in errors[:5]:
            print(f"    {err}", file=sys.stderr)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
