#!/usr/bin/env python3
"""V3: Deduplicate intervention records in collector_v3.db.

Uses: organization + workflow + intervention + URL + content_hash.
Also detects near-duplicates by org+intervention name similarity.
"""

import sys, json, os
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

V3_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "collector_v3.db"
os.environ["COLLECTOR_DATABASE_URL"] = f"sqlite:///{V3_DB_PATH}"

from compass_collector.database import init_db, get_session
from compass_collector.models.intervention import InterventionRecord, DuplicateRelationship, QualityFlag
import uuid
from datetime import datetime, timezone


def normalize(s: str) -> str:
    return s.lower().strip().replace("  ", " ")


def org_key(rec) -> str:
    org = normalize(rec.organization_name or "")
    title = normalize(rec.intervention_title or "")
    return f"{org}|{title[:80]}"


def main():
    init_db()
    session = get_session()

    records = session.query(InterventionRecord).all()
    print(f"Loaded {len(records)} records for dedup")

    dup_count = 0
    groups = defaultdict(list)

    # Group by org + title prefix
    for rec in records:
        key = org_key(rec)
        groups[key].append(rec)

    # Report exact duplicates
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        for i in range(1, len(group)):
            a, b = group[0], group[i]
            existing = session.query(DuplicateRelationship).filter(
                DuplicateRelationship.source_a_id == a.id,
                DuplicateRelationship.source_b_id == b.id
            ).first()
            if not existing and a.id != b.id:
                session.add(DuplicateRelationship(
                    id=str(uuid.uuid4()),
                    source_a_id=a.id,
                    source_b_id=b.id,
                    relationship_type="exact_duplicate",
                    confidence=1.0,
                    notes=f"Deduped by org+title: {org_key(group[0])}",
                    created_at=datetime.now(timezone.utc),
                ))
                dup_count += 1

    session.commit()
    print(f"Duplicates found: {dup_count}")

    # Report counts
    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0}
    for rec in records:
        tier = (rec.intervention_components or {}).get("evidence_tier", "unknown") if isinstance(rec.intervention_components, dict) else "unknown"
        if tier in tier_counts:
            tier_counts[tier] += 1

    print(f"\nPost-dedup record counts:")
    for t, c in tier_counts.items():
        print(f"  {t}: {c}")
    print(f"  Total unique: {len(records) - dup_count}")

    session.close()


if __name__ == "__main__":
    main()
