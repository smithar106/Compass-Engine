"""Comparable implementation retrieval engine.

Takes a query (workflow, department, company size, industry, intervention, desired outcome)
and returns the closest real implementations ranked by similarity.
"""

import json
from typing import Optional
from datetime import datetime
from compass_collector.database import get_session
from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord
from compass_collector.models.document import Document


SIMILARITY_WEIGHTS = {
    "problem_statement": 0.35,
    "workflow": 0.25,
    "intervention": 0.15,
    "industry": 0.10,
    "company_size": 0.10,
    "outcome": 0.05,
}


class ImplementationQuery:
    """Query parameters for finding comparable implementations."""

    def __init__(
        self,
        workflow: Optional[str] = None,
        business_function: Optional[str] = None,
        industry: Optional[str] = None,
        company_size_band: Optional[str] = None,
        employee_count: Optional[int] = None,
        intervention_category: Optional[str] = None,
        intervention_subcategory: Optional[str] = None,
        desired_outcome: Optional[str] = None,
        include_negative: bool = True,
        min_results: int = 5,
        max_results: int = 20,
    ):
        self.workflow = (workflow or "").lower()
        self.business_function = (business_function or "").lower()
        self.industry = (industry or "").lower()
        self.company_size_band = company_size_band
        self.employee_count = employee_count
        self.intervention_category = (intervention_category or "").lower()
        self.intervention_subcategory = (intervention_subcategory or "").lower()
        self.desired_outcome = (desired_outcome or "").lower()
        self.include_negative = include_negative
        self.min_results = min_results
        self.max_results = max_results


def _get_workflow(value: str) -> str:
    """Try to extract a workflow string from various sources."""
    if not value:
        return ""
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, list):
        return " ".join(value).lower()
    return str(value).lower()


def _get_business_function(record: InterventionRecord) -> str:
    """Extract business function from record."""
    bf = record.problem_business_function
    if bf and isinstance(bf, list) and len(bf) > 0:
        return bf[0].lower() if isinstance(bf[0], str) else ""
    if bf and isinstance(bf, str):
        return bf.lower()
    return ""


def _get_industries(record: InterventionRecord) -> list[str]:
    """Extract industry list from record."""
    ind = record.organization_industry
    if ind and isinstance(ind, list):
        return [str(i).lower() for i in ind]
    return []


def _get_outcome_categories(record: InterventionRecord, metrics: list[MetricRecord]) -> list[str]:
    """Extract outcome categories from metrics."""
    cats = set()
    for m in metrics:
        if m.metric_category:
            cats.add(m.metric_category.lower())
    return list(cats)


def _get_intervention_families(record: InterventionRecord) -> list[str]:
    """Extract intervention families."""
    families = record.intervention_families
    if families and isinstance(families, list):
        return [str(f).lower() for f in families]
    return []


def _get_components(record: InterventionRecord) -> dict:
    """Get intervention_components JSON field, safely."""
    comps = record.intervention_components
    if comps and isinstance(comps, str):
        try:
            return json.loads(comps)
        except (json.JSONDecodeError, TypeError):
            return {}
    if comps and isinstance(comps, dict):
        return comps
    return {}


def _employee_count_to_band(count: Optional[int]) -> str:
    """Map employee count to a size band."""
    if count is None:
        return ""
    if count < 10:
        return "<10"
    if count < 50:
        return "10-50"
    if count < 200:
        return "50-200"
    if count < 1000:
        return "200-1000"
    if count < 10000:
        return "1000-10000"
    return "10000+"


def _band_to_range(band: str) -> tuple[Optional[int], Optional[int]]:
    """Convert a size band string to min/max range."""
    mapping = {
        "<10": (0, 10),
        "10-50": (10, 50),
        "50-200": (50, 200),
        "200-1000": (200, 1000),
        "1000-10000": (1000, 10000),
        "10000+": (10000, None),
    }
    return mapping.get(band, (None, None))


def score_problem_similarity(query_workflow: str, record: InterventionRecord) -> float:
    """Score problem statement overlap — how similar is the described problem?"""
    if not query_workflow:
        return 0.0
    q = set(query_workflow.lower().split())
    # Build document from record's problem fields
    rec_parts = []
    if record.problem_statement:
        rec_parts.append(record.problem_statement.lower())
    if record.problem_baseline_description:
        rec_parts.append(record.problem_baseline_description.lower())
    if record.intervention_title:
        rec_parts.append(record.intervention_title.lower())
    if record.intervention_description:
        rec_parts.append(record.intervention_description.lower())
    rec_text = " ".join(rec_parts)
    rec_words = set(rec_text.split())
    if not rec_words:
        return 0.0
    overlap = q & rec_words
    # Jaccard with bonus for multi-word phrases
    jaccard = len(overlap) / max(len(q), len(rec_words))
    # Bonus for exact phrase matches (2-word and 3-word phrases)
    q_phrases = set()
    q_list = query_workflow.lower().split()
    for i in range(len(q_list)):
        if i + 1 < len(q_list):
            q_phrases.add(f"{q_list[i]} {q_list[i+1]}")
        if i + 2 < len(q_list):
            q_phrases.add(f"{q_list[i]} {q_list[i+1]} {q_list[i+2]}")
    phrase_matches = sum(1 for p in q_phrases if p in rec_text)
    phrase_bonus = min(0.3, phrase_matches * 0.1)
    return min(1.0, jaccard * 1.5 + phrase_bonus)


def score_workflow_similarity(query_workflow: str, record_workflow: str) -> float:
    """Score workflow match between query and record."""
    if not query_workflow or not record_workflow:
        return 0.0
    q = query_workflow.lower().strip()
    r = record_workflow.lower().strip()
    if q == r:
        return 1.0
    # Partial match — check if one contains the other
    if q in r or r in q:
        return 0.7
    # Word overlap
    q_words = set(q.replace("_", " ").replace("-", " ").split())
    r_words = set(r.replace("_", " ").replace("-", " ").split())
    if q_words and r_words:
        overlap = len(q_words & r_words)
        total = len(q_words | r_words)
        if total > 0:
            return 0.5 * (overlap / total)
    return 0.0


def score_company_similarity(query: ImplementationQuery, record: InterventionRecord) -> float:
    """Score company size similarity."""
    score = 0.0
    count = 0

    # Employee count proximity
    if query.employee_count and record.organization_employee_count:
        q_size = float(query.employee_count)
        r_size = float(record.organization_employee_count)
        ratio = min(q_size, r_size) / max(q_size, r_size) if max(q_size, r_size) > 0 else 0
        score += ratio
        count += 1

    # Size band match
    if query.company_size_band:
        q_band = query.company_size_band
        r_band = _employee_count_to_band(record.organization_employee_count)
        if r_band:
            if q_band == r_band:
                score += 1.0
                count += 1
            else:
                # Adjacent bands get partial credit
                bands = ["<10", "10-50", "50-200", "200-1000", "1000-10000", "10000+"]
                if q_band in bands and r_band in bands:
                    q_idx = bands.index(q_band)
                    r_idx = bands.index(r_band)
                    dist = abs(q_idx - r_idx)
                    if dist == 1:
                        score += 0.5
                        count += 1
                    elif dist == 2:
                        score += 0.2
                        count += 1

    return score / max(count, 1)


def score_industry_similarity(query: ImplementationQuery, record: InterventionRecord) -> float:
    """Score industry similarity."""
    if not query.industry:
        return 0.0
    q = query.industry.lower().strip()
    industries = _get_industries(record)
    if not industries:
        return 0.0
    for ind in industries:
        if q == ind:
            return 1.0
        if q in ind or ind in q:
            return 0.7
        # Word overlap
        q_words = set(q.replace("_", " ").replace("-", " ").split())
        r_words = set(ind.replace("_", " ").replace("-", " ").split())
        overlap = len(q_words & r_words)
        if overlap > 0:
            return 0.3
    return 0.0


def score_intervention_similarity(query: ImplementationQuery, record: InterventionRecord) -> float:
    """Score intervention type similarity."""
    score = 0.0
    count = 0

    families = _get_intervention_families(record)
    comps = _get_components(record)
    record_category = (comps.get("intervention_category") or "").lower()
    record_workflow = (comps.get("workflow") or "").lower()

    # Category match
    if query.intervention_category and record_category:
        if query.intervention_category == record_category:
            score += 1.0
        else:
            # Map old families to new categories
            cat_map = {
                "ai": ["predictive_ai", "generative_ai", "ai_assisted_work", "autonomous_ai", "human_in_the_loop_ai"],
                "software": ["new_software_implementation", "existing_software_optimization", "software"],
                "workflow_automation": ["workflow_simplification", "rules_based_automation", "robotic_process_automation", "rpa"],
                "process_redesign": ["process_redesign", "lean"],
                "staffing": ["staffing_increases", "staffing_reallocation", "outsourcing", "training"],
                "hybrid": ["hybrid_combination"],
            }
            q_cat = query.intervention_category
            for cat, old_fams in cat_map.items():
                if q_cat == cat:
                    if any(f in families for f in old_fams):
                        score += 0.6
                    break
        count += 1

    # Subcategory match
    if query.intervention_subcategory:
        if query.intervention_subcategory in families:
            score += 1.0
            count += 1
        elif any(query.intervention_subcategory in f for f in families):
            score += 0.5
            count += 1

    return score / max(count, 1)


def score_outcome_similarity(query: ImplementationQuery, record: InterventionRecord, metrics: list[MetricRecord]) -> float:
    """Score outcome category similarity."""
    if not query.desired_outcome:
        return 0.0
    q = query.desired_outcome.lower().strip()
    cats = _get_outcome_categories(record, metrics)
    if not cats:
        return 0.0
    for c in cats:
        if q == c:
            return 1.0
        if q in c or c in q:
            return 0.7
    return 0.0


def compute_similarity(query: ImplementationQuery, record: InterventionRecord, metrics: list[MetricRecord]) -> dict:
    """Compute full similarity score with breakdown."""
    comps = _get_components(record)
    record_workflow = comps.get("workflow") or ""

    ps_score = score_problem_similarity(query.workflow, record) * SIMILARITY_WEIGHTS["problem_statement"]
    wf_score = score_workflow_similarity(query.workflow, record_workflow) * SIMILARITY_WEIGHTS["workflow"]
    cs_score = score_company_similarity(query, record) * SIMILARITY_WEIGHTS["company_size"]
    ind_score = score_industry_similarity(query, record) * SIMILARITY_WEIGHTS["industry"]
    inv_score = score_intervention_similarity(query, record) * SIMILARITY_WEIGHTS["intervention"]
    out_score = score_outcome_similarity(query, record, metrics) * SIMILARITY_WEIGHTS["outcome"]

    total = ps_score + wf_score + cs_score + ind_score + inv_score + out_score

    return {
        "total": round(total, 3),
        "max_possible": sum(SIMILARITY_WEIGHTS.values()),
        "components": {
            "problem": {"raw": round(ps_score / SIMILARITY_WEIGHTS["problem_statement"], 2) if SIMILARITY_WEIGHTS["problem_statement"] else 0, "weighted": round(ps_score, 3)},
            "workflow": {"raw": round(wf_score / SIMILARITY_WEIGHTS["workflow"], 2) if SIMILARITY_WEIGHTS["workflow"] else 0, "weighted": round(wf_score, 3)},
            "company_size": {"raw": round(cs_score / SIMILARITY_WEIGHTS["company_size"], 2) if SIMILARITY_WEIGHTS["company_size"] else 0, "weighted": round(cs_score, 3)},
            "industry": {"raw": round(ind_score / SIMILARITY_WEIGHTS["industry"], 2) if SIMILARITY_WEIGHTS["industry"] else 0, "weighted": round(ind_score, 3)},
            "intervention": {"raw": round(inv_score / SIMILARITY_WEIGHTS["intervention"], 2) if SIMILARITY_WEIGHTS["intervention"] else 0, "weighted": round(inv_score, 3)},
            "outcome": {"raw": round(out_score / SIMILARITY_WEIGHTS["outcome"], 2) if SIMILARITY_WEIGHTS["outcome"] else 0, "weighted": round(out_score, 3)},
        },
    }


def summarize_outcomes(metrics: list[MetricRecord]) -> list[str]:
    """Create concise outcome summaries (e.g. 'Reduced cost 41%')."""
    summaries = []
    for m in metrics:
        if m.percentage_change is not None:
            pct = m.percentage_change
            change_label = f"{abs(pct):.0f}%"
            metric = m.metric_name or "Metric"
            cat = (m.metric_category or "").lower()

            # Determine if the change is positive (good) or negative (bad) for the organization
            is_absolute_improvement = False
            if pct < 0 and cat in ("cost", "time", "risk", "errors"):
                is_absolute_improvement = True  # cost/time/risk down = good
            elif pct > 0 and cat in ("revenue", "satisfaction", "adoption", "quality", "accuracy", "productivity", "efficiency", "growth", "conversion"):
                is_absolute_improvement = True  # revenue/satisfaction up = good
            elif pct > 0:
                # Generic positive metric
                is_absolute_improvement = True
            else:
                is_absolute_improvement = False

            summaries.append(f"{metric}: {change_label} {'improvement' if is_absolute_improvement else 'decline'}")
        elif m.absolute_change is not None:
            change = m.absolute_change
            metric = m.metric_name or "Metric"
            cat = (m.metric_category or "").lower()
            unit = m.unit or ""

            is_improvement = False
            if change < 0 and cat in ("cost", "time", "risk"):
                is_improvement = True
            elif change > 0 and cat in ("revenue", "satisfaction", "adoption", "quality"):
                is_improvement = True
            elif change > 0:
                is_improvement = True

            abs_change = abs(change)
            summaries.append(f"{metric}: {'+' if change > 0 else '-'}{abs_change:.0f} {unit} {'improvement' if is_improvement else 'decline'}".strip())
    return summaries[:3]


def summarize_intervention(record: InterventionRecord, metrics: list[MetricRecord]) -> str:
    """Create a one-line summary: 'Acme Corp reduced cost 41% via X'."""
    org = record.organization_name or "Organization"
    intervention = record.intervention_title or (record.intervention_description or "")[:60]
    intervention_short = intervention[:60] if intervention else "implementation"

    # Find best outcome
    best = None
    for m in metrics:
        if m.percentage_change is not None:
            direction = "positive"
            if m.metric_category == "cost" and m.percentage_change < 0:
                direction = "positive"
            elif m.metric_category in ("revenue", "satisfaction", "adoption") and m.percentage_change > 0:
                direction = "positive"
            change = abs(m.percentage_change)
            summary = f"{change:.0f}% {'improvement' if direction == 'positive' else 'decline'} in {m.metric_name or 'metric'}"
            if not best or change > best[1]:
                best = (summary, change)
        elif m.absolute_change is not None:
            summary = f"{'+' if m.absolute_change > 0 else ''}{m.absolute_change:.0f} {m.unit or ''} {m.metric_name or ''}".strip()
            if not best:
                best = (summary, 0)

    outcome = best[0] if best else "results"
    return f"{org} {outcome} via {intervention_short}"


def find_comparable_implementations(query: ImplementationQuery) -> dict:
    """Main retrieval function — finds comparable implementations matching the query.

    Stage 1: SQL pre-filter by business function / intervention category / status
    Stage 2: Python similarity scoring on the filtered candidate pool
    Stage 3: Organization deduplication
    """
    session = get_session()
    try:
        from sqlalchemy import or_

        # ── Stage 1: SQL pre-filter (53K → ~500–3000) ──
        q = session.query(InterventionRecord)

        # Governance gate (migration 2026-08-14): only published evidence is
        # retrievable for recommendations. Legacy published and claim-verified
        # published both pass; staging/quarantined/rejected are excluded.
        q = q.filter(InterventionRecord.publication_status == "published")

        # Hard filter: must have structured data
        q = q.filter(InterventionRecord.intervention_families != None)
        q = q.filter(InterventionRecord.intervention_families != "[]")

        # Business function filter — major reduction
        if query.business_function:
            q = q.filter(
                InterventionRecord.problem_business_function.like(
                    f'%"{query.business_function}"%'
                )
            )

        # Intervention family filter
        family_conditions = []
        if query.intervention_category:
            family_conditions.append(
                InterventionRecord.intervention_families.like(f'%"{query.intervention_category}"%')
            )
        if query.intervention_subcategory:
            family_conditions.append(
                InterventionRecord.intervention_families.like(f'%"{query.intervention_subcategory}"%')
            )
        if family_conditions:
            q = q.filter(or_(*family_conditions))

        # Status filter for non-negative queries
        if not query.include_negative:
            q = q.filter(
                ~InterventionRecord.result_status.in_(["failed", "abandoned"])
            )

        records = q.limit(5000).all()
        total = len(records)
        scored = []

        # ── Stage 2: Python similarity scoring ──
        # Batch-load all metrics for the filtered records
        record_ids = [r.id for r in records]
        metrics_map: dict = {}
        if record_ids:
            for chunk_start in range(0, len(record_ids), 500):
                chunk = record_ids[chunk_start:chunk_start + 500]
                for m in session.query(MetricRecord).filter(
                    MetricRecord.intervention_id.in_(chunk)
                ).all():
                    metrics_map.setdefault(m.intervention_id, []).append(m)

        # Batch-load documents (source URL/title) and passages for provenance.
        # Select only needed scalar columns to avoid JSON-deserialization errors
        # on legacy rows that may contain non-JSON values in JSON-typed columns.
        doc_map: dict = {}
        doc_ids = [r.document_id for r in records if r.document_id]
        if doc_ids:
            for row in session.query(Document.id, Document.url, Document.title).filter(
                Document.id.in_(doc_ids)
            ).all():
                doc_map[row[0]] = {"url": row[1], "title": row[2]}
        passage_map: dict = {}
        if record_ids:
            for row in session.query(PassageRecord.intervention_id, PassageRecord.passage_text).filter(
                PassageRecord.intervention_id.in_(record_ids)
            ).all():
                passage_map.setdefault(row[0], []).append({"passage_text": row[1]})

        for i, rec in enumerate(records):
            metrics = metrics_map.get(rec.id, [])
            similarity = compute_similarity(query, rec, metrics)
            if similarity["total"] > 0:
                scored.append({
                    "similarity": similarity,
                    "record": rec,
                    "metrics": metrics,
                })

        # Sort by similarity descending
        scored.sort(key=lambda x: -x["similarity"]["total"])

        # Take top results (oversample, then deduplicate by org)
        seen_orgs = set()
        results = []
        for s in scored:
            org = s["record"].organization_name or ""
            if org and org.lower() in seen_orgs:
                continue
            seen_orgs.add(org.lower())
            results.append(s)
            if len(results) >= query.max_results:
                break

        # If we don't have enough, include more without dedup
        if len(results) < query.min_results:
            for s in scored:
                if len(results) >= query.min_results:
                    break
                result_ids = {r["record"].id for r in results}
                if s["record"].id not in result_ids:
                    results.append(s)

        # Format output
        implementations = []
        for s in results:
            rec = s["record"]
            metrics = s["metrics"]
            comps = _get_components(rec)
            summaries = summarize_outcomes(metrics)
            neg_flags = []
            if rec.result_status in ("failed", "abandoned"):
                neg_flags.append("failed")
            if rec.vendor_reported:
                neg_flags.append("vendor_reported")

            doc = doc_map.get(rec.document_id)
            passages = passage_map.get(rec.id) or []
            supporting_passage = passages[0]["passage_text"] if passages else ""

            implementations.append({
                "id": rec.id,
                "organization": rec.organization_name or "Unknown",
                "industry": rec.organization_industry or [],
                "employee_count": rec.organization_employee_count,
                "size_band": _employee_count_to_band(rec.organization_employee_count),
                "problem": (rec.problem_statement or "")[:200],
                "intervention": rec.intervention_title or "",
                "intervention_families": rec.intervention_families or [],
                "workflow": comps.get("workflow", ""),
                "intervention_category": comps.get("intervention_category", ""),
                "status": rec.result_status or "unknown",
                "vendor_reported": rec.vendor_reported,
                "independently_verified": rec.independently_verified,
                "cost_savings": f"${rec.intervention_implementation_cost:,.0f}" if rec.intervention_implementation_cost else None,
                "implementation_time": f"{rec.intervention_implementation_time_value} {rec.intervention_implementation_time_unit or ''}" if rec.intervention_implementation_time_value else None,
                "outcome_summaries": summaries,
                "summary": summarize_intervention(rec, metrics),
                "similarity_score": round(s["similarity"]["total"] * 100),
                "similarity_breakdown": s["similarity"]["components"],
                "negatives": neg_flags,
                "lessons": (rec.failure_conditions or [])[:3] + (rec.implementation_challenges or [])[:2],
                # Provenance (migration 2026-08-14): source + verification exposed
                "source_url": doc["url"] if doc else "",
                "source_title": doc["title"] if doc else "",
                "supporting_passage": supporting_passage,
                "verification_status": rec.verification_status or "legacy",
            })

        # Aggregate stats
        total_comparable = len(scored)
        orgs = set()
        for s in scored:
            if s["record"].organization_name:
                orgs.add(s["record"].organization_name)
        statuses = {}
        for s in scored:
            st = s["record"].result_status or "unknown"
            statuses[st] = statuses.get(st, 0) + 1

        # Average evidence score among comparables
        evidence_scores = []
        for s in scored:
            eq = _get_components(s["record"]).get("evidence_quality") or {}
            # Rough evidence score from available data
            score = 50
            if s["record"].independently_verified:
                score += 20
            if s["record"].sample_size and s["record"].sample_size > 1:
                score += 10
            if s["metrics"]:
                quantified = sum(1 for m in s["metrics"] if m.percentage_change is not None or m.absolute_change is not None)
                score += min(20, quantified * 5)
            if s["record"].vendor_reported:
                score -= 15
            evidence_scores.append(max(0, min(100, score)))

        avg_evidence = round(sum(evidence_scores) / max(len(evidence_scores), 1))

        return {
            "query": {
                "workflow": query.workflow,
                "business_function": query.business_function,
                "industry": query.industry,
                "company_size_band": query.company_size_band,
                "intervention_category": query.intervention_category,
                "desired_outcome": query.desired_outcome,
            },
            "results": implementations,
            "total_found": len(scored),
            "total_returned": len(implementations),
            "unique_organizations": len(orgs),
            "status_breakdown": statuses,
            "average_evidence_score": avg_evidence,
            "negative_evidence_count": statuses.get("failed", 0) + statuses.get("abandoned", 0),
            "confidence_summary": f"Based on {len(scored)} comparable implementations, {len(orgs)} independent organizations",
        }

    finally:
        session.close()


def get_negative_evidence(query: ImplementationQuery = None) -> list[dict]:
    """Get failed/abandoned implementations specifically — negative evidence."""
    session = get_session()
    try:
        q = session.query(InterventionRecord).filter(
            InterventionRecord.result_status.in_(["failed", "abandoned"])
        )
        if query and query.workflow:
            pass  # We'd filter by workflow in a full implementation

        results = []
        for rec in q.limit(20).all():
            metrics = session.query(MetricRecord).filter_by(intervention_id=rec.id).all()
            failures = (rec.failure_conditions or [])[:3]
            challenges = (rec.implementation_challenges or [])[:3]
            results.append({
                "organization": rec.organization_name or "Unknown",
                "intervention": rec.intervention_title or "",
                "status": rec.result_status,
                "failure_reasons": failures + challenges,
                "problem": (rec.problem_statement or "")[:200],
                "lessons_learned": (rec.unintended_consequences or [])[:2],
            })
        return results
    finally:
        session.close()


def get_evidence_for_recommendation(
    workflow: str,
    business_function: str,
    industry: str = "",
    employee_count: int = None,
    intervention_category: str = "",
    desired_outcome: str = "",
) -> dict:
    """One-call function: 'Show me the evidence that supports this recommendation'."""
    query = ImplementationQuery(
        workflow=workflow,
        business_function=business_function,
        industry=industry,
        employee_count=employee_count,
        intervention_category=intervention_category,
        desired_outcome=desired_outcome,
    )
    comparable = find_comparable_implementations(query)
    negative = get_negative_evidence(query)

    return {
        "recommendation_context": {
            "workflow": workflow,
            "department": business_function,
            "industry": industry,
            "company_size": employee_count,
        },
        "comparable_implementations": comparable,
        "negative_evidence": negative,
        "why_summary": _generate_why_summary(comparable, negative),
    }


def _generate_why_summary(comparable: dict, negative: list[dict]) -> str:
    """Generate a human-readable 'Why this recommendation' summary."""
    lines = [f"Based on {comparable['total_found']} comparable implementations across {comparable['unique_organizations']} organizations."]

    if comparable["status_breakdown"].get("successful", 0) > comparable["total_found"] * 0.5:
        lines.append("Most implementations reported positive outcomes.")

    failed = comparable["negative_evidence_count"]
    if failed > 0:
        lines.append(f"{failed} similar implementations failed or were abandoned — their lessons are included below.")

    if comparable["results"]:
        lines.append("\nTop comparable implementations:")

    for r in comparable["results"][:5]:
        line = f"- {r['summary']}"
        if r["similarity_score"] >= 50:
            line += f" (similarity: {r['similarity_score']}%)"
        lines.append(line)

    if negative:
        lines.append("\nNotable failures:")
        for n in negative[:3]:
            reasons = "; ".join(n["failure_reasons"][:2])
            lines.append(f"- {n['organization']} attempted {n['intervention'][:60]}: {reasons}")

    return "\n".join(lines)
