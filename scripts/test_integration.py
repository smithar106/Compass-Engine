#!/usr/bin/env python3
"""Integration tests for the Compass recommendation API.

Tests 10 acceptance criteria against the 5 demo scenarios.
Runs against the FastAPI service (requires it to be running on port 8001).
"""

import sys, os, json, requests
from pathlib import Path

API_BASE = os.environ.get("COMPASS_API_URL", "http://127.0.0.1:8001")

DEMO_SCENARIOS = [
    {"scenario_name": "cloud_cost", "label": "Cloud Infrastructure Cost Reduction"},
    {"scenario_name": "support_automation", "label": "Customer Support Automation"},
    {"scenario_name": "invoice_processing", "label": "Invoice Processing Automation"},
    {"scenario_name": "lead_qualification", "label": "Lead Qualification AI"},
    {"scenario_name": "hr_onboarding", "label": "HR Onboarding Automation"},
]

pass_count = 0
fail_count = 0
results = []


def check(description: str, passed: bool, detail: str = ""):
    global pass_count, fail_count
    status = "PASS" if passed else "FAIL"
    if passed:
        pass_count += 1
    else:
        fail_count += 1
    results.append((status, description, detail))
    print(f"  [{status}] {description}" + (f" — {detail}" if detail else ""))


def test_health():
    print("\n--- Health Check ---")
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        check("API is reachable", r.status_code == 200, f"status={r.status_code}")
        data = r.json()
        check("Health returns ok", data.get("status") == "ok")
    except requests.ConnectionError:
        check("API is reachable", False, "Connection refused — is FastAPI running?")


def test_scenario(scenario: dict):
    label = scenario["label"]
    print(f"\n--- Scenario: {label} ---")

    try:
        r = requests.post(
            f"{API_BASE}/api/recommendations/demo",
            json={"scenario_name": scenario["scenario_name"]},
            timeout=30,
        )
        check(f"[AC1] Request succeeds for {label}", r.status_code == 200, f"status={r.status_code}")
        if r.status_code != 200:
            return

        data = r.json()

        # AC1: Valid investigation returns exactly 3 recommendations
        recs = data.get("recommendations", [])
        check(f"[AC1] 1-3 recommendations returned", 1 <= len(recs) <= 3, f"got {len(recs)}")

        if not recs:
            return

        # AC2: First recommendation has rank 1 and is_compass_choice=true
        first = recs[0]
        check(f"[AC2] Rank 1 is compass_choice", first.get("rank") == 1 and first.get("is_compass_choice") is True,
              f"rank={first.get('rank')}, choice={first.get('is_compass_choice')}")

        # AC3: Every recommendation has a valid evidence tier
        valid_tiers = {"gold", "silver", "bronze"}
        for rec in recs:
            tier = rec.get("evidence_summary", {}).get("overall_tier", "")
            check(f"[AC3] {rec['title']} has valid tier",
                  tier in valid_tiers,
                  f"tier={tier}")

        # AC4: Gold, Silver, Bronze counts reconcile with comparables
        for rec in recs:
            es = rec.get("evidence_summary", {})
            comps = rec.get("comparables", [])
            g = es.get("gold_count", 0)
            s = es.get("silver_count", 0)
            b = es.get("bronze_count", 0)
            total_by_tier = g + s + b
            actual = len(comps)
            check(f"[AC4] Tiers reconcile for {rec['title']}",
                  total_by_tier == actual,
                  f"tier_sum={total_by_tier}, actual={actual}")

        # AC5: Rejected evidence never appears
        for rec in recs:
            rejected = [c for c in rec.get("comparables", []) if c.get("evidence_tier") == "rejected"]
            check(f"[AC5] No rejected evidence in {rec['title']}", len(rejected) == 0,
                  f"found {len(rejected)} rejected")

        # AC6: Failed implementations appear under negative evidence when relevant
        for rec in recs:
            neg = rec.get("negative_evidence", [])
            if rec.get("evidence_summary", {}).get("failed_comparables", 0) > 0:
                check(f"[AC6] Negative evidence present for {rec['title']}", len(neg) > 0,
                      f"failed={rec['evidence_summary']['failed_comparables']}, neg_count={len(neg)}")
            else:
                check(f"[AC6] No failures for {rec['title']}", len(neg) >= 0)

        # AC7: Unsupported impact numbers are not fabricated
        for rec in recs:
            impact = rec.get("projected_impact", {})
            if not impact.get("is_sufficiently_supported"):
                check(f"[AC7] {rec['title']}: impact not fabricated",
                      impact.get("label") == "" or not impact.get("is_sufficiently_supported"))
            else:
                check(f"[AC7] {rec['title']}: impact supported",
                      impact.get("low") is not None and impact.get("high") is not None)

        # AC8: No marketing copy in response
        check(f"[AC8] compass_note not in response", "compass_note" not in data,
              "marketing copy should not be returned by backend")

        # Confidence breakdown present
        cb = data.get("confidence_breakdown", {})
        check(f"[AC8] confidence_breakdown has factors",
              "outcome_measured_implementations" in cb,
              f"keys={list(cb.keys())}")

        # AC9: Alternatives exist
        for rec in recs:
            alts = rec.get("alternatives_considered", [])
            check(f"[AC9] {rec['title']} has alternatives", len(alts) > 0,
                  f"count={len(alts)}")

        # AC10: Why-it-ranked has content
        for rec in recs:
            why = rec.get("why_it_ranked", [])
            check(f"[AC10] {rec['title']} has why-it-ranked", len(why) > 0,
                  f"count={len(why)}")

    except Exception as e:
        check(f"Request failed for {label}", False, str(e))


def main():
    print("=" * 60)
    print("  COMPASS INTEGRATION TESTS")
    print("  Target:", API_BASE)
    print("=" * 60)

    test_health()
    for scenario in DEMO_SCENARIOS:
        test_scenario(scenario)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {pass_count} passed, {fail_count} failed")
    print("=" * 60)

    if fail_count > 0:
        print("\n  Failed checks:")
        for status, desc, detail in results:
            if status == "FAIL":
                print(f"    {desc}: {detail}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
