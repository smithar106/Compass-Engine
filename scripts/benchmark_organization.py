#!/usr/bin/env python3
"""Organization/industry matching benchmark (before vs after).

Deliverable #6: retrieval-factor comparison. Runs a set of representative
queries through BOTH the legacy retrieval (raw industry string similarity) and
the new context-aware retrieval (canonical taxonomy + ten-factor fit), and
prints a side-by-side comparison.

Usage:
  ./venv/bin/python scripts/benchmark_organization.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.models.intervention import InterventionRecord  # noqa: E402,F401
from compass_collector.database import get_session  # noqa: E402
from compass_collector.organization.profile import resolve_organization  # noqa: E402
from compass_collector.analysis.context_retrieval import (  # noqa: E402
    ContextQuery,
    find_comparable_implementations_context,
)
from compass_collector.analysis.retrieval import (  # noqa: E402
    ImplementationQuery,
    find_comparable_implementations,
)

QUERIES = [
    {
        "name": "invoice_processing_bank",
        "company": "Stripe",
        "workflow": "invoice_processing",
        "business_function": "finance",
        "problem": "Manual invoice processing is slow and error-prone",
    },
    {
        "name": "support_healthcare",
        "company": "",
        "industry": "healthcare",
        "workflow": "ticketing",
        "business_function": "customer_support",
        "problem": "Support tickets pile up and resolution is slow",
    },
    {
        "name": "cloud_migration_tech",
        "company": "Shopify",
        "workflow": "cloud_migration",
        "business_function": "engineering",
        "problem": "Migrating workloads to the cloud",
    },
]


def _legacy_top(query: dict, records) -> list:
    q = ImplementationQuery(
        workflow=query.get("workflow", ""),
        business_function=query.get("business_function", ""),
        industry=query.get("industry", ""),
        max_results=5,
    )
    from compass_collector.analysis.retrieval import compute_similarity

    scored = []
    for r in records:
        from compass_collector.analysis.retrieval import _get_components

        comps = _get_components(r)
        record_workflow = comps.get("workflow") or ""
        sim = compute_similarity(q, r, [])
        if sim["total"] > 0:
            scored.append((sim["total"], r))
    scored.sort(key=lambda x: -x[0])
    return [
        {
            "org": getattr(r, "organization_name", "") or "Unknown",
            "industry": (getattr(r, "organization_industry", None) or [])[:1],
            "workflow": (_get_components(r).get("workflow") or "")[:40],
            "score": round(s, 3),
        }
        for s, r in scored[:5]
    ]


def main():
    session = get_session()
    try:
        records = session.query(InterventionRecord).all()
    finally:
        session.close()

    print("=" * 78)
    print("Organization / industry matching — retrieval comparison")
    print(f"Evidence records: {len(records)}")
    print("=" * 78)

    for query in QUERIES:
        print(f"\n### {query['name']}")
        print(f"    company={query.get('company','')} industry={query.get('industry','')} "
              f"workflow={query['workflow']} function={query['business_function']}")

        # BEFORE: legacy retrieval
        print("  BEFORE (legacy string similarity):")
        for row in _legacy_top(query, records):
            print(f"    {row['score']:>6.2f}  {row['org'][:28]:28s} ind={row['industry']}")

        # AFTER: context-aware retrieval
        resolved = resolve_organization(
            company_name=query.get("company", ""),
            industry=query.get("industry", ""),
        )
        cq = ContextQuery.from_profile(
            resolved.proposed.to_dict() if resolved.proposed else None,
            NS(workflow=query["workflow"], business_function=query["business_function"], problem_statement=query.get("problem", "")),
        )
        after = find_comparable_implementations_context(cq, records, max_results=5)
        print("  AFTER (context factors, canonical taxonomy):")
        for row in after["results"]:
            top_factors = sorted(
                ((k, v["raw"]) for k, v in row["fit_breakdown"].items()), key=lambda x: -x[1]
            )[:3]
            fac = ", ".join(f"{k}={v}" for k, v in top_factors)
            print(f"    {row['fit_total']:>6.3f}  {row['organization'][:28]:28s} factors({fac})")

    print("\nDone.")


class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


if __name__ == "__main__":
    main()
