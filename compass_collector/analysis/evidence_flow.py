"""Evidence-flow classification.

A record is usable by the recommendation engine only when it shows a clear
pre -> intervention -> post flow with attribution:

  PRE          has_baseline / problem_baseline_description / metric baseline_value
  INTERVENTION intervention_families AND intervention_title
  POST         metric post_value / percentage_change / absolute_change
  SOURCE       document_id present (resolvable source)
  ATTRIBUTION  outcome_provenance recorded

Records that do not meet all five are `archived`: retained in the DB but
excluded from retrieval (fail-closed).

`classify_evidence_flow(session)` is deterministic and idempotent; it is used by
the CLI script and by the engine's startup task.
"""

from __future__ import annotations

from collections import Counter


def classify_evidence_flow(session) -> dict:
    from compass_collector.models.intervention import InterventionRecord, MetricRecord

    metrics: dict = {}
    for m in session.query(MetricRecord).all():
        metrics.setdefault(m.intervention_id, []).append(m)

    records = session.query(InterventionRecord).all()

    def has_pre(r, ms) -> bool:
        return (
            bool(r.has_baseline)
            or bool(r.problem_baseline_description)
            or any(m.baseline_value is not None for m in ms)
        )

    def has_post(ms) -> bool:
        return any(
            m.post_value is not None
            or m.percentage_change is not None
            or m.absolute_change is not None
            for m in ms
        )

    flow_ids: list[str] = []
    tiers = Counter()
    keep_by_provenance = Counter()
    keep_by_source_type = Counter()

    for r in records:
        ms = metrics.get(r.id, [])
        pre, post = has_pre(r, ms), has_post(ms)
        interv = bool(r.intervention_families) and bool(r.intervention_title)
        src = bool(r.document_id)
        attr = bool(r.outcome_provenance)
        core = pre and post and interv
        if core:
            tiers["pre+intervention+post"] += 1
        if core and src:
            tiers["+source"] += 1
        if core and src and attr:
            tiers["+attribution (flow_complete)"] += 1
            flow_ids.append(r.id)
            keep_by_provenance[r.outcome_provenance or "none"] += 1
            keep_by_source_type[r.source_type or "none"] += 1

    return {
        "total": len(records),
        "tiers": dict(tiers),
        "flow_complete": len(flow_ids),
        "archived": len(records) - len(flow_ids),
        "keep_by_provenance": dict(keep_by_provenance),
        "keep_by_source_type": dict(keep_by_source_type),
        "flow_ids": flow_ids,
    }


def apply_evidence_flow(session) -> int:
    """Classify and persist evidence_status. Returns the number updated."""
    from compass_collector.models.intervention import InterventionRecord

    result = classify_evidence_flow(session)
    flow = set(result["flow_ids"])
    updated = 0
    for r in session.query(InterventionRecord).all():
        want = "flow_complete" if r.id in flow else "archived"
        if r.evidence_status != want:
            r.evidence_status = want
            updated += 1
    session.commit()
    return updated


def is_classified(session) -> bool:
    """True once at least one record is marked flow_complete."""
    from compass_collector.models.intervention import InterventionRecord

    try:
        return (
            session.query(InterventionRecord.id)
            .filter(InterventionRecord.evidence_status == "flow_complete")
            .first()
            is not None
        )
    except Exception:
        return False
