"""Evidence mode — the fail-closed verification gate.

Compass distinguishes two evidence modes so a large, partially-verified corpus
remains useful without ever presenting unverified material as verified:

  VERIFIED      — the record passed the complete verification bar
                  (verification_status == "claim_verified" AND a linked source).
                  Only verified evidence may support a factual claim presented
                  as verified.

  EXPLORATORY   — a sourced or classified record that has NOT completed
                  verification. Useful for exploration and hypotheses, always
                  labeled, and never represented as independently verified.

  INSUFFICIENT  — no linked source (or explicitly rejected). May not support
                  any factual claim.

Claim kinds used by the recommendation engine:

  finding       — supported by verified evidence
  hypothesis    — supported by exploratory evidence only
  assumption    — provided by the user (assessment inputs), not evidence

See docs/architecture_assessment.md and docs/named_company_risk_audit.md.
"""

from __future__ import annotations

from enum import Enum


class EvidenceMode(str, Enum):
    VERIFIED = "verified"
    EXPLORATORY = "exploratory"
    INSUFFICIENT = "insufficient"


class ClaimKind(str, Enum):
    FINDING = "finding"
    HYPOTHESIS = "hypothesis"
    ASSUMPTION = "assumption"


# Verification statuses that have completed the full bar. In the engine's
# single enum, "claim_verified" implies source_authentic + document_verified.
_FULLY_VERIFIED = {"claim_verified"}

# Statuses that are sourced/classified but not fully verified.
_PARTIAL = {"source_authentic", "document_verified", "legacy", "classified", "partial"}


def classify_evidence_mode(
    verification_status: str | None,
    source_url: str | None,
    supporting_passage: str | None = "",
) -> EvidenceMode:
    """Classify a record into an evidence mode. Fail-closed by default."""
    vs = (verification_status or "legacy").strip().lower()
    has_source = bool((source_url or "").strip())

    if vs == "rejected":
        return EvidenceMode.INSUFFICIENT

    if vs in _FULLY_VERIFIED and has_source:
        return EvidenceMode.VERIFIED

    # Sourced/classified but not fully verified → exploratory.
    if has_source and (vs in _PARTIAL or vs not in _FULLY_VERIFIED):
        return EvidenceMode.EXPLORATORY

    # No linked source → cannot support any claim.
    return EvidenceMode.INSUFFICIENT


def is_presentable_as_verified(
    verification_status: str | None,
    source_url: str | None,
    supporting_passage: str | None = "",
) -> bool:
    """Fail-closed gate: True only for fully verified, sourced evidence."""
    return classify_evidence_mode(verification_status, source_url, supporting_passage) == EvidenceMode.VERIFIED


def claim_kind_for_modes(modes: list[EvidenceMode]) -> ClaimKind:
    """Derive the claim kind for a statement from the evidence supporting it.

    Any verified support → finding. Exploratory support only → hypothesis.
    No evidence support → hypothesis (never presented as a verified finding).
    """
    if any(m == EvidenceMode.VERIFIED for m in modes):
        return ClaimKind.FINDING
    return ClaimKind.HYPOTHESIS


def dominant_mode(modes: list[EvidenceMode]) -> EvidenceMode:
    """The overall mode of a set of evidence: verified only if all verified."""
    if not modes:
        return EvidenceMode.INSUFFICIENT
    if all(m == EvidenceMode.VERIFIED for m in modes):
        return EvidenceMode.VERIFIED
    if any(m in (EvidenceMode.VERIFIED, EvidenceMode.EXPLORATORY) for m in modes):
        return EvidenceMode.EXPLORATORY
    return EvidenceMode.INSUFFICIENT
