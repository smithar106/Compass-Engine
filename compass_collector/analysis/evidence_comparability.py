"""Evidence comparability and outcome attribution.

TWO INDEPENDENT DIMENSIONS — never conflated:

  Source verification (see ``analysis/evidence_mode.py`` and the engine's
  ``verification_status``): is the document authentic and does it contain the
  cited claim? Values: source_authentic | document_verified | claim_verified.

  Comparability (this module): does the record document an implementation of
  the intervention being evaluated? Values: unassessed | direct_implementation
  | indirect_contextual | not_relevant.

A record can be claim_verified (source) and still be indirect_contextual or
not_relevant (comparability). Source verification never implies comparability.

Comparability is NOT inferred. It is assigned only by human/curated review and
defaults to ``unassessed``. It is never upgraded automatically from keyword
similarity, industry classification, or source verification.

Outcome attribution is a THIRD, separate check: even a source-verified,
directly comparable record may not establish that the intervention *caused* the
reported outcome. Attribution values: unassessed | explicit | uncertain | none.

Fail-closed rule: a record may support a claim that the intervention produced an
outcome ONLY when comparability == direct_implementation AND attribution ==
explicit. Everything else (unassessed, indirect_contextual, not_relevant, or
uncertain/none attribution) fails closed.
"""

from __future__ import annotations

from enum import Enum


class Comparability(str, Enum):
    UNASSESSED = "unassessed"
    DIRECT_IMPLEMENTATION = "direct_implementation"
    INDIRECT_CONTEXTUAL = "indirect_contextual"
    NOT_RELEVANT = "not_relevant"


class OutcomeAttribution(str, Enum):
    UNASSESSED = "unassessed"
    EXPLICIT = "explicit"   # source explicitly links intervention -> outcome
    UNCERTAIN = "uncertain"  # plausible but not established by the source
    NONE = "none"            # source does not link them


# Records that must never support a direct-implementation outcome claim.
_FAIL_CLOSED_COMPARABILITY = {
    Comparability.UNASSESSED,
    Comparability.INDIRECT_CONTEXTUAL,
    Comparability.NOT_RELEVANT,
}

_FAIL_CLOSED_ATTRIBUTION = {
    OutcomeAttribution.UNASSESSED,
    OutcomeAttribution.UNCERTAIN,
    OutcomeAttribution.NONE,
}


def parse_comparability(value: str | None) -> Comparability:
    """Parse a stored comparability value; unknown/empty → unassessed (fail closed)."""
    try:
        return Comparability((value or "").strip().lower())
    except ValueError:
        return Comparability.UNASSESSED


def parse_attribution(value: str | None) -> OutcomeAttribution:
    """Parse a stored attribution value; unknown/empty → unassessed (fail closed)."""
    try:
        return OutcomeAttribution((value or "").strip().lower())
    except ValueError:
        return OutcomeAttribution.UNASSESSED


def supports_direct_outcome_claim(
    comparability: str | Comparability | None,
    attribution: str | OutcomeAttribution | None,
) -> bool:
    """Fail-closed gate: True only for direct implementation with explicit attribution.

    Any other combination — including unassessed — returns False.
    """
    comp = comparability if isinstance(comparability, Comparability) else parse_comparability(comparability)
    attr = attribution if isinstance(attribution, OutcomeAttribution) else parse_attribution(attribution)
    if comp in _FAIL_CLOSED_COMPARABILITY:
        return False
    if attr in _FAIL_CLOSED_ATTRIBUTION:
        return False
    return comp == Comparability.DIRECT_IMPLEMENTATION and attr == OutcomeAttribution.EXPLICIT


def attribution_limitation(
    comparability: str | Comparability | None,
    attribution: str | OutcomeAttribution | None,
) -> str:
    """Human-readable limitation when a record cannot support a direct-outcome claim."""
    comp = comparability if isinstance(comparability, Comparability) else parse_comparability(comparability)
    attr = attribution if isinstance(attribution, OutcomeAttribution) else parse_attribution(attribution)

    if comp == Comparability.UNASSESSED:
        return "Comparability not yet reviewed."
    if comp == Comparability.NOT_RELEVANT:
        return "Not relevant to this decision."
    if comp == Comparability.INDIRECT_CONTEXTUAL:
        return "Indirect context only — does not document this intervention."
    if attr == OutcomeAttribution.UNASSESSED:
        return "Outcome attribution not yet reviewed."
    if attr == OutcomeAttribution.UNCERTAIN:
        return "The source does not establish that the intervention produced this outcome."
    if attr == OutcomeAttribution.NONE:
        return "The source does not link the intervention to this outcome."
    return ""
