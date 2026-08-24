"""Canonical workflow relations — the reconciliation layer between the query
vocabulary and the record vocabulary.

Problem being solved (root cause):
  Queries carry a canonical workflow slug (e.g. ``invoice_processing`` from
  ``_infer_workflow`` or the prototype problem definitions), while records
  carry BOTH verbose free text (``intervention_components.workflow``) and a
  canonical tag (``workflow_normalized.value``) that frequently uses a
  *different* slug for the same domain (e.g. ``accounts_payable``,
  ``procurement``, ``order_to_cash``). The old ``score_workflow_similarity``
  only rewarded exact/contained/word-overlap matches, so substantively
  relevant records scored near zero on the workflow factor and fell below the
  retrieval threshold.

This module is a deterministic data-engineering fix, not an ML/embedding
change:

  * a single canonical workflow vocabulary (reusing ``ALL_WORKFLOWS``)
  * explicit ALIAS (equivalent) and RELATED (nearby domain) graphs, plus the
    DB-observed vocabulary folded into those graphs
  * a typed relation ``WorkflowRelation`` (EXACT / ALIAS / RELATED /
    PARTIAL_TEXT / UNRELATED) with deterministic scores
  * explainability: every scored match reports its match type and the
    specific workflows that matched

Relationship strengths are explicit, not inferred: an alias is NOT treated as
identical to a related workflow, and unrelated workflows never match.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from compass_collector.analysis.comparability import ALL_WORKFLOWS

# ---------------------------------------------------------------------------
# Relation types and scores (deterministic).
# ---------------------------------------------------------------------------


class WorkflowRelation(str, Enum):
    EXACT = "exact"          # same canonical slug
    ALIAS = "alias"          # different slug, same domain (equivalent)
    RELATED = "related"      # adjacent domain, clearly relevant
    PARTIAL_TEXT = "partial_text"  # free-text overlap only (fallback)
    UNRELATED = "unrelated"

    @property
    def score(self) -> float:
        return {
            WorkflowRelation.EXACT: 1.0,
            WorkflowRelation.ALIAS: 0.9,
            WorkflowRelation.RELATED: 0.55,
            WorkflowRelation.PARTIAL_TEXT: 0.35,
            WorkflowRelation.UNRELATED: 0.0,
        }[self]


# ---------------------------------------------------------------------------
# Relationship graph.
#
# Keys are canonical slugs. Values are sets of slugs treated as ALIAS (same
# domain) or RELATED (adjacent domain). Both canonical ALL_WORKFLOWS slugs and
# observed record-side vocabulary (e.g. ``order_to_cash``, ``contact_center``)
# may appear on the right-hand side; the lookup normalizes record tags onto
# their canonical form where possible.
# ---------------------------------------------------------------------------

WORKFLOW_ALIASES: dict[str, set[str]] = {
    # ---- invoice processing (prototype problem 2) ----
    "invoice_processing": {
        "invoice_processing",
        "accounts_payable",
        "accounts_receivable",
        "invoicing",
        "billing",
        "revenue_cycle_management",
        "purchase_order",
        "procure_to_pay",
        "payables",
    },
    "accounts_payable": {
        "invoice_processing",
        "accounts_payable",
        "purchase_order",
        "procure_to_pay",
        "payables",
    },

    # ---- onboarding (prototype problems 1 & 10) ----
    "onboarding": {
        "onboarding",
        "employee_onboarding",
        "customer_onboarding",
        "new_hire",
        "new_hiring",
        "onboarding_automation",
        "ramp",
        "learning_development",
    },
    "learning_development": {
        "onboarding",
        "learning_development",
        "training",
        "employee_training",
        "new_hire",
    },

    # ---- support routing (prototype problem 3) ----
    "ticketing": {
        "ticketing",
        "helpdesk",
        "help_desk",
        "support_ticket",
        "ticket_management",
        "it_service_desk",
        "service_desk",
    },
    "call_routing": {
        "call_routing",
        "contact_center",
        "call_center",
        "customer_service",
        "call_handling",
        "inbound_calls",
        "routing",
        "ivr",
    },

    # ---- knowledge management (prototype problems 4 & 9) ----
    "knowledge_base": {
        "knowledge_base",
        "knowledge_management",
        "document_management",
        "information_retrieval",
        "self_service",
        "faq_management",
        "content_management",
        "knowledge_retrieval",
    },
    "document_management": {
        "knowledge_base",
        "document_management",
        "knowledge_management",
        "information_retrieval",
        "document_search",
    },

    # ---- handoff / order-to-cash (prototype problem 5) ----
    "order_processing": {
        "order_processing",
        "order_fulfillment",
        "order_to_cash",
        "order_to_cash_otc",
        "quote_to_order",
        "quote_to_cash",
        "sales_order",
        "order_management",
    },
    "order_fulfillment": {
        "order_processing",
        "order_fulfillment",
        "order_to_cash",
        "fulfillment",
    },

    # ---- reporting (prototype problem 6) ----
    "analytics_reporting": {
        "analytics_reporting",
        "reporting",
        "report_automation",
        "business_intelligence",
        "data_reporting",
        "analytics",
        "dashboard",
    },
    "financial_reporting": {
        "financial_reporting",
        "reporting",
        "financial_close",
        "month_end_close",
        "management_reporting",
    },

    # ---- escalation / churn (prototype problem 7) ----
    "relationship_management": {
        "relationship_management",
        "customer_health",
        "customer_health_scoring",
        "churn",
        "churn_management",
        "customer_retention",
        "account_planning",
        "escalation",
        "at_risk",
        "client_relationship",
    },
    "customer_journey": {
        "relationship_management",
        "customer_health",
        "customer_journey",
        "churn",
        "customer_retention",
    },

    # ---- forecasting (prototype problem 8) ----
    "forecasting": {
        "forecasting",
        "demand_forecasting",
        "demand_planning",
        "sales_forecasting",
        "financial_forecasting",
        "budgeting",
        "revenue_forecasting",
    },
    "demand_forecasting": {
        "forecasting",
        "demand_forecasting",
        "demand_planning",
    },

    # ---- enterprise search (prototype problem 9, thin) ----
    "self_service": {
        "self_service",
        "knowledge_base",
        "knowledge_management",
        "enterprise_search",
        "information_retrieval",
        "search",
        "faq",
    },
}

WORKFLOW_RELATED: dict[str, set[str]] = {
    # invoice / finance domain
    "invoice_processing": {
        "financial_reporting",
        "reconciliation",
        "expense_management",
        "general_ledger",
        "procurement",
        "supplier_management",
        "order_to_cash",
        "financial_consolidation",
    },
    "accounts_payable": {
        "financial_reporting",
        "reconciliation",
        "expense_management",
        "procurement",
        "supplier_management",
    },

    # onboarding / HR domain
    "onboarding": {
        "recruiting",
        "employee_engagement",
        "benefits_administration",
        "performance_management",
        "compliance_training",
        "knowledge_base",
        "self_service",
    },
    "learning_development": {
        "onboarding",
        "recruiting",
        "employee_engagement",
        "performance_management",
    },

    # support domain
    "ticketing": {
        "call_routing",
        "chat",
        "self_service",
        "knowledge_base",
        "claims_processing",
        "email_processing",
        "customer_journey",
    },
    "call_routing": {
        "ticketing",
        "chat",
        "self_service",
        "knowledge_base",
        "claims_processing",
        "email_processing",
        "relationship_management",
    },

    # knowledge domain
    "knowledge_base": {
        "ticketing",
        "call_routing",
        "chat",
        "self_service",
        "team_collaboration",
        "data_pipeline",
        "onboarding",
    },
    "document_management": {
        "knowledge_base",
        "self_service",
        "data_pipeline",
        "data_curation",
        "team_collaboration",
    },

    # handoff domain
    "order_processing": {
        "ecommerce",
        "lead_qualification",
        "contract_management",
        "proposal_generation",
        "pipeline_management",
        "customer_journey",
        "logistics",
        "order_fulfillment",
    },
    "order_fulfillment": {
        "logistics",
        "warehouse_management",
        "inventory_management",
        "ecommerce",
        "order_processing",
    },

    # reporting domain
    "analytics_reporting": {
        "financial_reporting",
        "regulatory_reporting",
        "data_pipeline",
        "data_warehousing",
        "master_data_management",
        "budgeting",
        "quality_control",
    },
    "financial_reporting": {
        "analytics_reporting",
        "regulatory_reporting",
        "budgeting",
        "financial_consolidation",
        "general_ledger",
        "data_warehousing",
    },

    # escalation / churn domain
    "relationship_management": {
        "call_routing",
        "ticketing",
        "customer_journey",
        "personalization",
        "sentiment_analysis",
        "analytics_reporting",
        "data_curation",
    },
    "customer_journey": {
        "call_routing",
        "ticketing",
        "relationship_management",
        "personalization",
        "campaign_management",
    },

    # forecasting domain
    "forecasting": {
        "inventory_management",
        "inventory_optimization",
        "budgeting",
        "financial_consolidation",
        "master_data_management",
        "scm_implementation",
        "supplier_management",
        "logistics",
    },
    "demand_forecasting": {
        "inventory_management",
        "inventory_optimization",
        "supplier_management",
        "logistics",
        "scm_implementation",
    },

    # enterprise search domain
    "self_service": {
        "ticketing",
        "chat",
        "knowledge_base",
        "document_management",
        "team_collaboration",
    },
}

# ---------------------------------------------------------------------------
# Normalization helpers.
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _SLUG_RE.sub("_", str(value or "").strip().lower()).strip("_")


def normalize_record_tag(raw_tag: str) -> str:
    """Normalize a record-side workflow tag onto a canonical slug.

    Handles the DB-observed vocabulary that is not in ``ALL_WORKFLOWS`` by
    folding it onto its canonical alias when known, otherwise returning the
    slugified raw value (never dropped).
    """
    if not raw_tag:
        return ""
    cleaned = _slug(raw_tag)
    if cleaned in ALL_WORKFLOWS:
        return cleaned
    # Non-canonical observed vocabulary → canonical.
    for canonical, aliases in WORKFLOW_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return cleaned


def _resolve_alias_lookup() -> dict[str, set[str]]:
    """Build slug → {canonical slugs it is an alias of}."""
    lookup: dict[str, set[str]] = {}
    for canonical, aliases in WORKFLOW_ALIASES.items():
        for a in aliases:
            lookup.setdefault(a, set()).add(canonical)
    return lookup


_ALIAS_LOOKUP = _resolve_alias_lookup()


def _resolve_related_lookup() -> dict[str, set[str]]:
    """Build slug → {canonical slugs it is related to}."""
    lookup: dict[str, set[str]] = {}
    for canonical, related in WORKFLOW_RELATED.items():
        for r in related:
            lookup.setdefault(r, set()).add(canonical)
    return lookup


_RELATED_LOOKUP = _resolve_related_lookup()


def canonical_workflows_for(raw_tag: str) -> set[str]:
    """All canonical workflows a record tag maps to (alias + related + self)."""
    if not raw_tag:
        return set()
    slug = _slug(raw_tag)
    if slug not in ALL_WORKFLOWS:
        slug = normalize_record_tag(slug)
    out = {slug} if slug in ALL_WORKFLOWS else set()
    out |= _ALIAS_LOOKUP.get(slug, set())
    out |= _RELATED_LOOKUP.get(slug, set())
    return out


# ---------------------------------------------------------------------------
# Deterministic workflow matching with explainability.
# ---------------------------------------------------------------------------


def resolve_query_workflow(query_workflow: str) -> str:
    """Normalize a query workflow onto a canonical slug when possible."""
    cleaned = _slug(query_workflow)
    if cleaned in ALL_WORKFLOWS:
        return cleaned
    for canonical, aliases in WORKFLOW_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return cleaned


def score_workflow_relation(
    query_workflow: str,
    record_workflow: str = "",
    record_canonical: str = "",
) -> dict:
    """Score workflow relation between a query and a record.

    Args:
        query_workflow: canonical query workflow slug (or free text).
        record_workflow: verbose record workflow free text (components.workflow).
        record_canonical: record's canonical tag (workflow_normalized.value).

    Returns:
        {
          "score": float,
          "match_type": WorkflowRelation,
          "matched_workflows": [canonical slugs that matched],
          "query_canonical": str,
          "record_canonical": str,
        }
    """
    q_canonical = resolve_query_workflow(query_workflow)
    r_canonical = normalize_record_tag(record_canonical or "")

    # 1. EXACT — same canonical slug.
    if q_canonical and r_canonical and q_canonical == r_canonical:
        return {
            "score": WorkflowRelation.EXACT.score,
            "match_type": WorkflowRelation.EXACT,
            "matched_workflows": [q_canonical],
            "query_canonical": q_canonical,
            "record_canonical": r_canonical,
        }

    # 2. ALIAS — query canonical is an alias of the record tag (or vice versa).
    if q_canonical and r_canonical:
        if r_canonical in _ALIAS_LOOKUP.get(q_canonical, set()) or q_canonical in _ALIAS_LOOKUP.get(r_canonical, set()):
            return {
                "score": WorkflowRelation.ALIAS.score,
                "match_type": WorkflowRelation.ALIAS,
                "matched_workflows": [q_canonical, r_canonical],
                "query_canonical": q_canonical,
                "record_canonical": r_canonical,
            }

    # 3. RELATED — adjacent domain.
    if q_canonical and r_canonical:
        if r_canonical in _RELATED_LOOKUP.get(q_canonical, set()) or q_canonical in _RELATED_LOOKUP.get(r_canonical, set()):
            return {
                "score": WorkflowRelation.RELATED.score,
                "match_type": WorkflowRelation.RELATED,
                "matched_workflows": [q_canonical, r_canonical],
                "query_canonical": q_canonical,
                "record_canonical": r_canonical,
            }

    # 4. Free-text partial overlap (existing behavior, retained as fallback).
    # Only applied when we have actual text and no canonical relation won.
    partial = _partial_text_score(query_workflow, record_workflow)
    if partial > 0:
        return {
            "score": partial,
            "match_type": WorkflowRelation.PARTIAL_TEXT,
            "matched_workflows": [],
            "query_canonical": q_canonical,
            "record_canonical": r_canonical,
        }

    return {
        "score": WorkflowRelation.UNRELATED.score,
        "match_type": WorkflowRelation.UNRELATED,
        "matched_workflows": [],
        "query_canonical": q_canonical,
        "record_canonical": r_canonical,
    }


def _partial_text_score(query_workflow: str, record_workflow: str) -> float:
    """Fallback: token/phrase overlap between query and record free text."""
    if not query_workflow or not record_workflow:
        return 0.0
    q = query_workflow.lower().strip()
    r = record_workflow.lower().strip()
    if q == r:
        return WorkflowRelation.EXACT.score
    if q in r or r in q:
        return 0.7
    q_words = set(q.replace("_", " ").replace("-", " ").split())
    r_words = set(r.replace("_", " ").replace("-", " ").split())
    if q_words and r_words:
        overlap = len(q_words & r_words)
        total = len(q_words | r_words)
        if total > 0:
            return min(0.5, 0.5 * (overlap / total))
    return 0.0


# Backward-compatible function used by tests and callers that only pass text.
def score_workflow_similarity(query_workflow: str, record_workflow: str) -> float:
    """Backward-compatible workflow similarity (free text only)."""
    return score_workflow_relation(query_workflow, record_workflow, "")["score"]
