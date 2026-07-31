"""Deterministic confidence scoring.

Calculates recommendation confidence from live graph statistics.
No LLM-generated values. Every input is traceable to the evidence graph.

Confidence = f(outcome_strength, evidence_quality, implementation_depth,
               consistency, diversity, risk_penalty)

All components return 0-100. Final score is weighted average,
clamped to [0, 100].
"""

from dataclasses import dataclass, field


@dataclass
class ConfidenceInputs:
    """Inputs for confidence calculation, all from live graph."""
    total_evidence: int = 0
    gold_count: int = 0
    silver_count: int = 0
    bronze_count: int = 0
    outcome_records: int = 0
    measured_outcomes: int = 0        # has baseline AND post
    independent_count: int = 0
    vendor_count: int = 0
    implementation_rich: int = 0       # 2+ implementation fields
    unique_orgs: int = 0
    negative_count: int = 0
    risk_count: int = 0
    has_contradictory: bool = False


@dataclass
class ConfidenceScore:
    """Deterministic confidence result."""
    overall: float               # 0-100
    label: str                   # strong / moderate / limited / insufficient
    components: dict             # individual component scores
    trace: list[dict]            # how each component was calculated


# Weights for each confidence component
WEIGHTS = {
    "outcome_strength": 0.30,
    "evidence_quality": 0.25,
    "implementation_depth": 0.20,
    "consistency": 0.15,
    "diversity": 0.10,
}


def compute_confidence(inputs: ConfidenceInputs) -> ConfidenceScore:
    """Compute deterministic confidence from graph statistics."""
    components = {}
    trace = []

    # 1. Outcome strength (0-100): how many measured outcomes exist
    outcome = _score_outcome_strength(inputs)
    components["outcome_strength"] = outcome["score"]
    trace.append(outcome)

    # 2. Evidence quality (0-100): tier mix and independence
    quality = _score_evidence_quality(inputs)
    components["evidence_quality"] = quality["score"]
    trace.append(quality)

    # 3. Implementation depth (0-100): rollout/partner/lessons detail
    depth = _score_implementation_depth(inputs)
    components["implementation_depth"] = depth["score"]
    trace.append(depth)

    # 4. Consistency (0-100): all positive vs mixed outcomes
    consistency = _score_consistency(inputs)
    components["consistency"] = consistency["score"]
    trace.append(consistency)

    # 5. Diversity (0-100): unique orgs, source types
    diversity = _score_diversity(inputs)
    components["diversity"] = diversity["score"]
    trace.append(diversity)

    # Weighted average
    raw = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)

    # Risk penalty: contradictory or negative evidence reduces confidence
    risk_penalty = _risk_penalty(inputs)
    raw = max(0, raw - risk_penalty)

    overall = round(min(100, max(0, raw)))

    if overall >= 70:
        label = "strong"
    elif overall >= 45:
        label = "moderate"
    elif overall >= 20:
        label = "limited"
    else:
        label = "insufficient"

    return ConfidenceScore(
        overall=overall,
        label=label,
        components=components,
        trace=trace,
    )


def _score_outcome_strength(inputs: ConfidenceInputs) -> dict:
    """Score based on quantity and quality of measured outcomes."""
    if inputs.total_evidence == 0:
        return {"score": 0, "reason": "no evidence", "inputs": {"total_evidence": 0}}

    # Measured outcomes (baseline+post) are the strongest signal
    measured_ratio = inputs.measured_outcomes / max(1, inputs.total_evidence)
    outcome_density = inputs.outcome_records / max(1, inputs.total_evidence)

    # Scoring curve
    score = 0
    if inputs.measured_outcomes >= 10:
        score = 90 + min(10, inputs.measured_outcomes - 10)
    elif inputs.measured_outcomes >= 5:
        score = 70 + (inputs.measured_outcomes - 5) * 4
    elif inputs.measured_outcomes >= 3:
        score = 50 + (inputs.measured_outcomes - 3) * 10
    elif inputs.measured_outcomes >= 1:
        score = 25 + (inputs.measured_outcomes - 1) * 12.5
    else:
        # No measured outcomes: check for any outcomes
        if inputs.outcome_records >= 3:
            score = 20
        elif inputs.outcome_records >= 1:
            score = 10

    return {
        "score": min(100, score),
        "reason": f"{inputs.measured_outcomes} measured outcomes out of {inputs.total_evidence} records ({measured_ratio:.0%} measured)",
        "inputs": {
            "measured_outcomes": inputs.measured_outcomes,
            "total_evidence": inputs.total_evidence,
            "measured_ratio": round(measured_ratio, 3),
        },
    }


def _score_evidence_quality(inputs: ConfidenceInputs) -> dict:
    """Score based on tier mix and source independence."""
    total = max(1, inputs.total_evidence)
    gold_ratio = inputs.gold_count / total
    ind_ratio = inputs.independent_count / total
    vendor_ratio = inputs.vendor_count / total

    # Gold provides strongest quality signal
    score = 0
    score += min(50, gold_ratio * 80)
    score += min(30, ind_ratio * 50)
    score -= min(20, vendor_ratio * 30)
    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "reason": f"{inputs.gold_count} gold, {inputs.independent_count} independent, {inputs.vendor_count} vendor out of {total}",
        "inputs": {
            "gold_count": inputs.gold_count,
            "silver_count": inputs.silver_count,
            "independent_count": inputs.independent_count,
            "vendor_count": inputs.vendor_count,
        },
    }


def _score_implementation_depth(inputs: ConfidenceInputs) -> dict:
    """Score based on availability of implementation detail."""
    if inputs.total_evidence == 0:
        return {"score": 0, "reason": "no evidence", "inputs": {}}

    impl_ratio = inputs.implementation_rich / max(1, inputs.total_evidence)
    if inputs.implementation_rich >= 5:
        score = 90
    elif inputs.implementation_rich >= 3:
        score = 70
    elif inputs.implementation_rich >= 1:
        score = 40
    else:
        score = 0

    return {
        "score": min(100, score),
        "reason": f"{inputs.implementation_rich} records with implementation detail ({impl_ratio:.0%})",
        "inputs": {
            "implementation_rich": inputs.implementation_rich,
            "impl_ratio": round(impl_ratio, 3),
        },
    }


def _score_consistency(inputs: ConfidenceInputs) -> dict:
    """Score based on outcome consistency across evidence."""
    if inputs.total_evidence == 0:
        return {"score": 0, "reason": "no evidence", "inputs": {}}

    total = inputs.total_evidence
    neg_ratio = (inputs.negative_count + inputs.risk_count) / max(1, total)

    if inputs.has_contradictory:
        score = max(0, 60 - neg_ratio * 100)
    elif neg_ratio > 0.3:
        score = max(0, 80 - neg_ratio * 80)
    elif neg_ratio > 0.1:
        score = 85
    else:
        score = 100

    return {
        "score": round(score, 1),
        "reason": f"{inputs.negative_count} negative, {inputs.risk_count} risk out of {total} ({neg_ratio:.0%})",
        "inputs": {
            "negative_count": inputs.negative_count,
            "risk_count": inputs.risk_count,
            "negative_ratio": round(neg_ratio, 3),
            "has_contradictory": inputs.has_contradictory,
        },
    }


def _score_diversity(inputs: ConfidenceInputs) -> dict:
    """Score based on organization and source diversity."""
    if inputs.total_evidence == 0:
        return {"score": 0, "reason": "no evidence", "inputs": {}}

    if inputs.unique_orgs >= 10:
        score = 100
    elif inputs.unique_orgs >= 5:
        score = 70 + (inputs.unique_orgs - 5) * 6
    elif inputs.unique_orgs >= 3:
        score = 50
    elif inputs.unique_orgs >= 1:
        score = 25
    else:
        score = 0

    return {
        "score": min(100, score),
        "reason": f"{inputs.unique_orgs} unique organizations",
        "inputs": {
            "unique_orgs": inputs.unique_orgs,
        },
    }


def _risk_penalty(inputs: ConfidenceInputs) -> float:
    """Penalty for contradictory or heavily negative evidence."""
    penalty = 0.0
    if inputs.has_contradictory:
        penalty += 15
    neg_ratio = (inputs.negative_count + inputs.risk_count) / max(1, inputs.total_evidence)
    if neg_ratio > 0.5:
        penalty += 20
    elif neg_ratio > 0.3:
        penalty += 10
    elif neg_ratio > 0.1:
        penalty += 5
    return penalty


def compute_inputs_from_package(package: dict) -> ConfidenceInputs:
    """Extract ConfidenceInputs from an assembled evidence package."""
    tier = package.get("tier_breakdown", {})
    gold = sum(tier.get(r, {}).get("gold", 0) for r in tier)
    silver = sum(tier.get(r, {}).get("silver", 0) for r in tier)
    bronze = sum(tier.get(r, {}).get("bronze", 0) for r in tier)
    impl = package.get("implementation_depth", 0)
    outcome = package.get("outcome_evidence_count", 0)
    risk = package.get("risk_evidence_count", 0)

    packages = package.get("packages", {})
    all_items = []
    for items in packages.values():
        all_items.extend(items)

    orgs = set()
    independent = 0
    vendor = 0
    measured = 0
    for item in all_items:
        org = item.get("organization", "")
        if org:
            orgs.add(org)
        if item.get("independently_verified"):
            independent += 1
        if item.get("vendor_reported"):
            vendor += 1
        if item.get("has_baseline") and item.get("has_post_measurement"):
            measured += 1

    total = len(all_items)

    return ConfidenceInputs(
        total_evidence=total,
        gold_count=gold,
        silver_count=silver,
        bronze_count=bronze,
        outcome_records=outcome,
        measured_outcomes=measured,
        independent_count=independent,
        vendor_count=vendor,
        implementation_rich=impl,
        unique_orgs=len(orgs),
        negative_count=0,
        risk_count=risk,
        has_contradictory=False,
    )
