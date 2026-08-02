#!/usr/bin/env python3
"""Organization-context benchmark against the enriched production database.

Item 2 of the organization/industry follow-up. Reports:
  - per-field coverage (industry, subsector, employee band, geography,
    operational function, workflow) from the live engine DB;
  - retrieval context scores and rankings for the same operational problem
    across four organization profiles;
  - whether company context changes recommendations, comparables, risks, or
    implementation patterns;
  - whether workflow + problem fit still dominate broad industry matching.

Usage:
  ./venv/bin/python scripts/benchmark_organization_enriched.py \
      --engine https://compass-engine-production-532b.up.railway.app
"""

import argparse
import json
import sys
import urllib.request

PROBLEM = {
    "business_function": "finance",
    "workflow": "invoice_processing",
    "problem_statement": "Manual invoice processing is slow and error prone; matching errors cause rework and payment delays.",
    "desired_outcome": "time",
}

PROFILES = [
    {"label": "No org (baseline)", "industry": "", "company_size": ""},
    {"label": "Stripe (fintech)", "industry": "fintech", "company_size": "1000"},
    {"label": "Walmart (retail)", "industry": "retail", "company_size": "10000"},
    {"label": "Hospital (healthcare)", "industry": "healthcare", "company_size": "5000"},
]


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def summarize_decision(decision: dict) -> dict:
    recs = decision.get("recommendations") or []
    top = recs[0] if recs else {}
    comparables = top.get("comparable_implementations") or []
    return {
        "top_category": top.get("category", ""),
        "top_title": top.get("title", ""),
        "confidence": (top.get("confidence") or {}).get("label", ""),
        "confidence_score": round((top.get("confidence") or {}).get("score", 0), 2),
        "evidence_tier": (top.get("evidence_summary") or {}).get("overall_tier", ""),
        "total_comparables": (top.get("evidence_summary") or {}).get("total_comparables", 0),
        "comparable_orgs": [c.get("organization", "") for c in comparables[:5]],
        "comparable_industries": sorted({str(i) for c in comparables[:8] for i in (c.get("organization_industry") or [])}),
        "risk_titles": [r.get("title", "") for r in (decision.get("risks") or [])][:4],
        "implementation_patterns": sorted({p for c in comparables[:8] for p in (c.get("implementation_pattern") or [])}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="https://compass-engine-production-532b.up.railway.app")
    args = parser.parse_args()

    engine = args.engine.rstrip("/")
    print("=" * 78)
    print("Organization-context benchmark against enriched production DB")
    print(f"Engine: {engine}")
    print("=" * 78)

    # 1) Coverage report from the live DB
    try:
        cov = _get(f"{engine}/api/evidence/coverage")
        print("\n## 1. Field coverage (live enriched DB)")
        print(f"  total records: {cov.get('total_records')}  | agent-enriched: {cov.get('agent_enriched_records')}")
        print(f"  raw industry values: {cov['coverage']['industry_raw_unique']} (unique, before normalization)")
        for field, v in cov["coverage"].items():
            if isinstance(v, dict) and "n" in v:
                print(f"  {field:26s} {v['n']:5d}  ({v['pct']}%)")
        print("\n  canonical industry top:")
        for k, n in (cov.get("canonical_industry_top") or [])[:10]:
            print(f"    {n:5d}  {k}")
    except Exception as exc:
        print(f"\n  !! coverage endpoint failed: {exc}")

    # 2) Same problem, four organization profiles
    print("\n## 2. Retrieval changes across four organization profiles (same problem)")
    decisions = {}
    for profile in PROFILES:
        payload = dict(PROBLEM)
        payload["industry"] = profile["industry"]
        payload["company_size"] = profile["company_size"]
        try:
            decision = _post(f"{engine}/api/recommendations", payload)
        except Exception as exc:
            print(f"  !! {profile['label']}: engine error {exc}")
            continue
        decisions[profile["label"]] = decision
        s = summarize_decision(decision)
        print(f"\n  --- {profile['label']} ---")
        print(f"    top: {s['top_category']} | {s['top_title'][:60]}")
        print(f"    confidence: {s['confidence_score']} ({s['confidence']}) | tier: {s['evidence_tier']} | comparables: {s['total_comparables']}")
        print(f"    comparable orgs: {s['comparable_orgs']}")
        print(f"    comparable industries: {s['comparable_industries']}")
        print(f"    risks: {s['risk_titles']}")
        print(f"    implementation patterns: {s['implementation_patterns']}")

    # 3) Does company context change anything vs baseline?
    print("\n## 3. Company-context effect vs baseline")
    baseline = decisions.get("No org (baseline)")
    if baseline:
        base = summarize_decision(baseline)
        for label, d in decisions.items():
            if label == "No org (baseline)" or d is None:
                continue
            s = summarize_decision(d)
            top_changed = s["top_category"] != base["top_category"] or s["top_title"] != base["top_title"]
            comp_changed = s["comparable_orgs"] != base["comparable_orgs"]
            risk_changed = s["risk_titles"] != base["risk_titles"]
            print(f"  {label:28s} top:{'CHANGED' if top_changed else 'same'}  comparables:{'CHANGED' if comp_changed else 'same'}  risks:{'CHANGED' if risk_changed else 'same'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
