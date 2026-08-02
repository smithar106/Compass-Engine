"""Canonical organization and industry matching.

Implements the organization/industry upgrade: controlled taxonomies,
normalization with provenance, company resolution, backfill, context-aware
retrieval factors, and the /api/organizations/resolve endpoint.
"""

from __future__ import annotations

from compass_collector.organization.taxonomy import normalize_industry
from compass_collector.organization.profile import OrganizationProfile, resolve_organization

__all__ = ["normalize_industry", "OrganizationProfile", "resolve_organization"]
