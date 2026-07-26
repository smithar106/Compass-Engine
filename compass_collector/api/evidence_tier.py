from compass_collector.models.intervention import InterventionRecord, MetricRecord, PassageRecord


EVIDENCE_TIER_GOLD = "gold"
EVIDENCE_TIER_SILVER = "silver"
EVIDENCE_TIER_BRONZE = "bronze"
EVIDENCE_TIER_REJECTED = "rejected"


def classify_evidence_tier(
    record: InterventionRecord,
    metrics: list[MetricRecord],
    passages: list[PassageRecord] | None = None,
) -> str:
    if _is_academic_or_vendor_only(record):
        return EVIDENCE_TIER_REJECTED

    has_real_org = bool(record.organization_name and not record.organization_anonymized)
    was_deployed = record.result_status not in ("unknown", "theoretical", "proposed")
    has_measurable_outcome = _has_quantified_metric(metrics)
    has_source_link = bool(passages) or bool(record.source_id)
    has_baseline = bool(record.has_baseline) or bool(record.problem_baseline_description)
    has_timeframe = bool(record.intervention_measurement_period_value)
    has_sample_size = record.sample_size is not None and record.sample_size > 1
    is_independent = bool(record.independently_verified)
    is_vendor = bool(record.vendor_reported)

    gold_score = 0
    if has_real_org:
        gold_score += 2
    if was_deployed:
        gold_score += 2
    if has_measurable_outcome:
        gold_score += 2
    if has_source_link:
        gold_score += 1
    if has_baseline:
        gold_score += 1
    if has_timeframe:
        gold_score += 1
    if has_sample_size:
        gold_score += 1
    if is_independent:
        gold_score += 2
    if is_vendor:
        gold_score -= 2

    if gold_score >= 8:
        return EVIDENCE_TIER_GOLD
    if gold_score >= 4:
        return EVIDENCE_TIER_SILVER
    if gold_score >= 1:
        return EVIDENCE_TIER_BRONZE

    return EVIDENCE_TIER_REJECTED


def _is_academic_or_vendor_only(record: InterventionRecord) -> bool:
    if not record.organization_name:
        return True
    org_lower = (record.organization_name or "").lower()
    academic_keywords = ["university", "college", "institute of", "school of", "research lab", "academic"]
    if any(k in org_lower for k in academic_keywords) and not record.independently_verified:
        return True
    return False


def _has_quantified_metric(metrics: list[MetricRecord]) -> bool:
    for m in metrics:
        if m.percentage_change is not None:
            return True
        if m.absolute_change is not None and m.absolute_change != 0:
            return True
    return False


def classify_tier_for_comparable(comparable: dict) -> str:
    org = comparable.get("organization", "")
    org_lower = org.lower()
    if not org or any(k in org_lower for k in ["university", "college", "research"]):
        return EVIDENCE_TIER_BRONZE

    outcomes = comparable.get("outcomes") or comparable.get("outcome_summaries") or []
    has_outcome = bool(outcomes)
    status = comparable.get("status", "unknown")
    similarity = comparable.get("similarity_score", 0)
    negatives = comparable.get("negatives", [])
    is_vendor = "vendor_reported" in negatives

    gold_score = 0
    if org and org != "Unknown" and not any(k in org_lower for k in ["university", "college", "research", "anonymous"]):
        gold_score += 2
    if status in ("successful", "partial", "implemented", "live"):
        gold_score += 2
    if has_outcome:
        gold_score += 2
    if not is_vendor:
        gold_score += 1
    if similarity >= 60:
        gold_score += 1
    if comparable.get("independently_verified"):
        gold_score += 2
    if comparable.get("cost_savings") or comparable.get("implementation_time"):
        gold_score += 1
    if comparable.get("employee_count") and comparable["employee_count"] > 0:
        gold_score += 1

    if gold_score >= 8:
        return EVIDENCE_TIER_GOLD
    if gold_score >= 4:
        return EVIDENCE_TIER_SILVER
    return EVIDENCE_TIER_BRONZE
