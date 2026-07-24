"""Evidence scoring system — computes an Evidence Score (0-100) for each intervention."""

from datetime import datetime, timezone
from compass_collector.models.intervention import InterventionRecord, MetricRecord
from compass_collector.database import get_session


EVIDENCE_WEIGHTS = {
    "source_credibility": 15,
    "measured_outcomes": 25,
    "outcome_impact": 20,
    "sample_size": 5,
    "independent_validation": 10,
    "outcome_specificity": 10,
    "recency": 5,
    "comparables": 10,
}


def score_source_credibility(record: InterventionRecord) -> tuple[float, str]:
    """Score based on who reported this evidence."""
    if record.vendor_reported:
        return 0.3, "vendor_reported"
    if record.independently_verified:
        return 1.0, "independently_verified"
    if record.organization_type in ("government", "academic", "healthcare", "nonprofit"):
        return 0.8, "non_vendor_org_type"
    if record.organization_type == "company" and not record.vendor_reported:
        return 0.6, "self_reported_company"
    return 0.5, "unknown_source"


def score_measured_outcomes(record: InterventionRecord, metrics: list[MetricRecord]) -> tuple[float, str]:
    """Score based on quantity and quality of measured outcomes."""
    if not metrics:
        return 0.0, "no_outcomes"

    has_baseline = any(m.baseline_value is not None for m in metrics)
    has_post = any(m.post_value is not None for m in metrics)
    has_percentage = any(m.percentage_change is not None for m in metrics)
    has_absolute = any(m.absolute_change is not None for m in metrics)

    outcome_count = len(metrics)
    observed_count = sum(1 for m in metrics if m.value_type == "observed")

    score = 0.0
    if outcome_count >= 3:
        score = 1.0
    elif outcome_count >= 2:
        score = 0.8
    elif outcome_count >= 1:
        score = 0.5

    # Bonus for having both baseline AND post
    if has_baseline and has_post:
        score = min(1.0, score + 0.2)
    if has_percentage:
        score = min(1.0, score + 0.1)
    if has_absolute:
        score = min(1.0, score + 0.1)

    details = f"{outcome_count} outcomes"
    if observed_count:
        details += f", {observed_count} observed"
    return score, details


def score_outcome_impact(record: InterventionRecord, metrics: list[MetricRecord]) -> tuple[float, str]:
    """Score whether the evidence shows real business impact vs mere adoption.
    Penalizes adoption-only evidence (tool deployed, no outcome measured).
    Rewards sustained, measured business outcomes."""
    if not metrics:
        return 0.0, "no_outcomes_measured_adoption_only"

    has_quantified_change = any(
        m.percentage_change is not None or m.absolute_change is not None
        for m in metrics
    )
    has_baseline = any(m.baseline_value is not None for m in metrics)
    has_sustained = any(
        m.time_period and ("month" in str(m.time_period).lower() or "year" in str(m.time_period).lower() or "quarter" in str(m.time_period).lower())
        for m in metrics
    )
    has_positive_outcome = any(
        (m.percentage_change is not None and m.percentage_change != 0) or
        (m.absolute_change is not None and m.absolute_change != 0)
        for m in metrics
    )

    if not has_quantified_change:
        return 0.1, "adoption_only_no_quantified_outcome"

    score = 0.5
    if has_baseline:
        score += 0.2
    if has_sustained:
        score += 0.2
    if has_positive_outcome:
        score = min(1.0, score + 0.1)

    details_parts = []
    if has_quantified_change:
        details_parts.append("has_quantified_change")
    if has_baseline:
        details_parts.append("pre_post_baseline")
    if has_sustained:
        details_parts.append("sustained_outcome")

    return score, "|".join(details_parts) if details_parts else "adoption_only"


def score_sample_size(record: InterventionRecord) -> tuple[float, str]:
    """Score based on sample size / organization count."""
    n = record.sample_size
    if n is None or n == 0:
        return 0.3, "no_sample_size"
    if n >= 1000:
        return 1.0, f"n={n}"
    if n >= 100:
        return 0.8, f"n={n}"
    if n >= 10:
        return 0.6, f"n={n}"
    return 0.4, f"n={n}"


def score_independent_validation(record: InterventionRecord) -> tuple[float, str]:
    """Score based on independent verification."""
    if record.independently_verified:
        return 1.0, "independently_verified"
    if not record.vendor_reported:
        return 0.6, "non_vendor"
    return 0.2, "vendor_only"


def score_outcome_specificity(record: InterventionRecord, metrics: list[MetricRecord]) -> tuple[float, str]:
    """Score based on how specific and quantified the outcomes are."""
    if not metrics:
        return 0.0, "no_metrics"

    has_numerical = 0
    for m in metrics:
        if m.percentage_change is not None or m.absolute_change is not None:
            has_numerical += 1

    ratio = has_numerical / len(metrics) if metrics else 0
    if ratio >= 0.8:
        return 1.0, f"{has_numerical}/{len(metrics)} quantified"
    if ratio >= 0.5:
        return 0.7, f"{has_numerical}/{len(metrics)} quantified"
    if ratio >= 0.1:
        return 0.4, f"{has_numerical}/{len(metrics)} quantified"
    return 0.1, "no_quantified_outcomes"


def score_recency(record: InterventionRecord) -> tuple[float, str]:
    """Score based on recency of the intervention."""
    if not record.extracted_at:
        return 0.5, "unknown_date"
    days_old = (datetime.now(timezone.UTC) - record.extracted_at).days
    if days_old <= 30:
        return 1.0, "last_30_days"
    if days_old <= 90:
        return 0.9, "last_90_days"
    if days_old <= 365:
        return 0.7, "last_year"
    if days_old <= 730:
        return 0.5, "last_2_years"
    return 0.3, "older_than_2_years"


def score_comparables(record: InterventionRecord, total_comparables: int = 0) -> tuple[float, str]:
    """Score based on number of comparable implementations."""
    if total_comparables >= 100:
        return 1.0, f"{total_comparables}+_comparable"
    if total_comparables >= 50:
        return 0.8, f"{total_comparables}_comparable"
    if total_comparables >= 10:
        return 0.6, f"{total_comparables}_comparable"
    if total_comparables >= 1:
        return 0.4, f"{total_comparables}_comparable"
    return 0.2, "no_comparables"


def compute_evidence_score(
    record: InterventionRecord,
    metrics: list[MetricRecord] = None,
    total_comparables: int = 0,
) -> dict:
    """Compute evidence score (0-100) with component breakdown."""
    if metrics is None:
        session = get_session()
        try:
            metrics = session.query(MetricRecord).filter_by(intervention_id=record.id).all()
        finally:
            session.close()

    components = {}

    sc, sc_detail = score_source_credibility(record)
    components["source_credibility"] = {"raw": sc, "weighted": sc * EVIDENCE_WEIGHTS["source_credibility"], "detail": sc_detail}

    mo, mo_detail = score_measured_outcomes(record, metrics)
    components["measured_outcomes"] = {"raw": mo, "weighted": mo * EVIDENCE_WEIGHTS["measured_outcomes"], "detail": mo_detail}

    ss, ss_detail = score_sample_size(record)
    components["sample_size"] = {"raw": ss, "weighted": ss * EVIDENCE_WEIGHTS["sample_size"], "detail": ss_detail}

    iv, iv_detail = score_independent_validation(record)
    components["independent_validation"] = {"raw": iv, "weighted": iv * EVIDENCE_WEIGHTS["independent_validation"], "detail": iv_detail}

    oi, oi_detail = score_outcome_impact(record, metrics)
    components["outcome_impact"] = {"raw": oi, "weighted": oi * EVIDENCE_WEIGHTS["outcome_impact"], "detail": oi_detail}

    os_, os_detail = score_outcome_specificity(record, metrics)
    components["outcome_specificity"] = {"raw": os_, "weighted": os_ * EVIDENCE_WEIGHTS["outcome_specificity"], "detail": os_detail}

    rec, rec_detail = score_recency(record)
    components["recency"] = {"raw": rec, "weighted": rec * EVIDENCE_WEIGHTS["recency"], "detail": rec_detail}

    comp, comp_detail = score_comparables(record, total_comparables)
    components["comparables"] = {"raw": comp, "weighted": comp * EVIDENCE_WEIGHTS["comparables"], "detail": comp_detail}

    total = sum(c["weighted"] for c in components.values())
    max_possible = sum(EVIDENCE_WEIGHTS.values())

    return {
        "evidence_score": round(total / max_possible * 100),
        "total_weighted": round(total, 1),
        "max_possible": max_possible,
        "components": components,
    }


def score_all_interventions() -> list[dict]:
    """Compute evidence scores for all interventions in the DB."""
    session = get_session()
    try:
        records = session.query(InterventionRecord).all()
        total = len(records)

        results = []
        for i, rec in enumerate(records):
            metrics = session.query(MetricRecord).filter_by(intervention_id=rec.id).all()
            score = compute_evidence_score(rec, metrics, total_comparables=total)
            results.append({
                "intervention_id": rec.id,
                "title": rec.intervention_title,
                "evidence_score": score["evidence_score"],
                "components": score["components"],
            })
            if (i + 1) % 100 == 0:
                print(f"  Scored {i+1}/{total}")

        return results
    finally:
        session.close()
