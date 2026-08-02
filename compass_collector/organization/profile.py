"""Canonical organization profile + company resolution (Phase 2 + Phase 4).

An ``OrganizationProfile`` carries every organization dimension with per-field
provenance (raw value, normalized value, source, explicit|inferred, confidence,
version). ``resolve_organization`` implements the resolution order:

1. Internal organization registry
2. Exact domain or alias match
3. Existing evidence-graph organization
4. Configured external enrichment / public-data tool (pluggable)
5. LLM-assisted structured classification (pluggable fallback)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from compass_collector.organization.registry import (
    CURATED_REGISTRY,
    lookup_by_domain,
    lookup_by_name,
)
from compass_collector.organization.taxonomy import (
    NormalizedValue,
    normalize_employee_count,
    normalize_geography,
    normalize_industry,
    normalize_operational_function,
    regulatory_intensity_for,
)

LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc|inc\.|incorporated|corp|corp\.|corporation|llc|ltd|ltd\.|limited|plc|"
    r"ag|gmbh|sa|co|co\.|company|group|holdings|holding|s\.a\.|s\.p\.a\.|p\.c\.)\b\.?$",
    re.IGNORECASE,
)


def clean_company_name(raw: str) -> str:
    """Strip legal suffixes and collapse whitespace for matching."""
    if not raw:
        return ""
    name = re.sub(r"\s+", " ", str(raw).strip())
    name = LEGAL_SUFFIX_RE.sub("", name).strip()
    name = re.sub(r"\s*&\s*$", "", name).strip()  # "JP Morgan Chase &" -> "JP Morgan Chase"
    return name


def clean_domain(raw: str) -> str:
    if not raw:
        return ""
    dom = str(raw).strip().lower().lstrip("www.").rstrip("/")
    return dom


@dataclass
class OrganizationProfile:
    organization_id: str = ""
    canonical_name: str = ""
    aliases: list[str] = field(default_factory=list)
    domain: str = ""
    # Per-field provenance: field name -> NormalizedValue
    fields: dict[str, NormalizedValue] = field(default_factory=dict)
    source_provenance: list[dict] = field(default_factory=list)
    user_confirmed: list[str] = field(default_factory=list)

    # -- convenience accessors --------------------------------------------
    @property
    def primary_industry(self) -> Optional[str]:
        nv = self.fields.get("primary_industry")
        return nv.value if nv and nv.value else None

    @property
    def industry_subsector(self) -> Optional[str]:
        nv = self.fields.get("industry_subsector")
        return nv.value if nv and nv.value else None

    @property
    def broader_industry(self) -> Optional[str]:
        nv = self.fields.get("broader_industry")
        return nv.value if nv and nv.value else None

    @property
    def business_model(self) -> Optional[str]:
        nv = self.fields.get("business_model")
        return nv.value if nv and nv.value else None

    @property
    def employee_band(self) -> Optional[str]:
        nv = self.fields.get("employee_band")
        return nv.value if nv and nv.value else None

    @property
    def revenue_band(self) -> Optional[str]:
        nv = self.fields.get("revenue_band")
        return nv.value if nv and nv.value else None

    @property
    def headquarters_country(self) -> Optional[str]:
        nv = self.fields.get("headquarters_country")
        return nv.value if nv and nv.value else None

    @property
    def operating_geographies(self) -> list[str]:
        nv = self.fields.get("operating_geographies")
        if not nv or not nv.value:
            return []
        return [g.strip() for g in nv.value.split(",") if g.strip()]

    @property
    def regulatory_context(self) -> Optional[str]:
        nv = self.fields.get("regulatory_context")
        return nv.value if nv and nv.value else None

    @property
    def technology_posture(self) -> Optional[str]:
        nv = self.fields.get("technology_posture")
        return nv.value if nv and nv.value else None

    @property
    def operational_functions(self) -> list[str]:
        nv = self.fields.get("operational_functions")
        if not nv or not nv.value:
            return []
        return [f.strip() for f in nv.value.split(",") if f.strip()]

    def field_confidence(self, field_name: str) -> float:
        nv = self.fields.get(field_name)
        return nv.confidence if nv else 0.0

    def fields_requiring_confirmation(self, threshold: float = 0.7) -> list[str]:
        return [
            name
            for name, nv in self.fields.items()
            if nv.value and nv.confidence < threshold
        ]

    def to_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "canonical_name": self.canonical_name,
            "aliases": self.aliases,
            "domain": self.domain,
            "fields": {
                name: nv.to_dict() for name, nv in self.fields.items() if nv.value
            },
            "primary_industry": self.primary_industry,
            "industry_subsector": self.industry_subsector,
            "broader_industry": self.broader_industry,
            "business_model": self.business_model,
            "employee_band": self.employee_band,
            "revenue_band": self.revenue_band,
            "headquarters_country": self.headquarters_country,
            "operating_geographies": self.operating_geographies,
            "regulatory_context": self.regulatory_context,
            "technology_posture": self.technology_posture,
            "operational_functions": self.operational_functions,
            "source_provenance": self.source_provenance,
            "user_confirmed": self.user_confirmed,
            "fields_requiring_confirmation": self.fields_requiring_confirmation(),
        }


@dataclass
class ResolutionResult:
    proposed: Optional[OrganizationProfile] = None
    alternatives: list[dict] = field(default_factory=list)
    confidence: dict = field(default_factory=dict)
    resolution_path: list[str] = field(default_factory=list)
    ambiguous: bool = False

    def to_dict(self) -> dict:
        return {
            "proposed": self.proposed.to_dict() if self.proposed else None,
            "alternatives": self.alternatives,
            "confidence": self.confidence,
            "resolution_path": self.resolution_path,
            "ambiguous": self.ambiguous,
            "fields_requiring_confirmation": (
                self.proposed.fields_requiring_confirmation() if self.proposed else []
            ),
        }


def _set_field(profile: OrganizationProfile, name: str, nv: NormalizedValue) -> None:
    if nv and nv.value:
        profile.fields[name] = nv


def _profile_from_registry(entry: dict, source: str) -> OrganizationProfile:
    p = OrganizationProfile(
        organization_id=f"reg-{entry['canonical_name'].lower().replace(' ', '-')}",
        canonical_name=entry["canonical_name"],
        aliases=list(entry.get("aliases", [])),
        domain=entry.get("domains", [""])[0],
    )
    p.source_provenance.append({"step": source, "source": "registry"})
    if entry.get("industry"):
        _set_field(
            p,
            "primary_industry",
            NormalizedValue(raw=entry["industry"], value=entry["industry"], source=source, confidence=0.95),
        )
        _set_field(
            p,
            "broader_industry",
            NormalizedValue(raw=entry["industry"], value=entry["industry"], source=source, confidence=0.95),
        )
    if entry.get("subsector"):
        _set_field(
            p,
            "industry_subsector",
            NormalizedValue(raw=entry["subsector"], value=entry["subsector"], source=source, confidence=0.9),
        )
    if entry.get("business_model"):
        _set_field(
            p,
            "business_model",
            NormalizedValue(raw=entry["business_model"], value=entry["business_model"], source=source, confidence=0.8),
        )
    if entry.get("regulatory_context"):
        _set_field(
            p,
            "regulatory_context",
            NormalizedValue(raw=entry["regulatory_context"], value=entry["regulatory_context"], source=source, confidence=0.8),
        )
    if entry.get("headquarters_country"):
        _set_field(
            p,
            "headquarters_country",
            NormalizedValue(raw=entry["headquarters_country"], value=entry["headquarters_country"], source=source, confidence=0.8),
        )
    if entry.get("operating_geographies"):
        _set_field(
            p,
            "operating_geographies",
            NormalizedValue(
                raw=", ".join(entry["operating_geographies"]),
                value=", ".join(entry["operating_geographies"]),
                source=source,
                confidence=0.8,
            ),
        )
    return p


def _profile_from_industry_text(company_name: str, industry: str, domain: str = "") -> OrganizationProfile:
    """Build a minimal profile from company/industry text (deterministic)."""
    norm = normalize_industry(industry) if industry else None
    p = OrganizationProfile(
        canonical_name=clean_company_name(company_name) if company_name else "",
        domain=clean_domain(domain),
    )
    if p.canonical_name:
        p.source_provenance.append({"step": "user_provided_name", "source": "user"})
    if norm and norm.mapped:
        _set_field(p, "primary_industry", NormalizedValue(raw=industry, value=norm.canonical, source="taxonomy", confidence=norm.confidence))
        _set_field(p, "industry_subsector", NormalizedValue(raw=industry, value=norm.subsector or "", source="taxonomy", confidence=norm.confidence * 0.9))
        _set_field(p, "broader_industry", NormalizedValue(raw=industry, value=norm.broader or "", source="taxonomy", confidence=norm.confidence))
        reg = regulatory_intensity_for(norm.canonical)
        if reg:
            _set_field(p, "regulatory_context", NormalizedValue(raw=industry, value=reg, source="taxonomy", method="inferred", confidence=0.6))
        p.source_provenance.append({"step": "taxonomy_classification", "source": "taxonomy", "industry_raw": industry})
    return p


def _evidence_match(session, cleaned_name: str) -> Optional[dict]:
    """Find an existing evidence-graph organization by normalized name."""
    from compass_collector.models.intervention import InterventionRecord

    if session is None:
        return None
    rows = (
        session.query(InterventionRecord.organization_name)
        .filter(InterventionRecord.organization_name.isnot(None))
        .all()
    )
    # index by cleaned name
    index: dict[str, str] = {}
    for (name,) in rows:
        idx = clean_company_name(name).lower()
        if idx:
            index.setdefault(idx, name)
    orig = index.get(cleaned_name.lower())
    if not orig:
        return None
    return {"canonical_name": orig, "source": "evidence_graph"}


def resolve_organization(
    company_name: str = "",
    company_domain: str = "",
    industry: str = "",
    *,
    session=None,
    enrich: Optional[Callable[[OrganizationProfile], OrganizationProfile]] = None,
    classify: Optional[Callable[[str, str], OrganizationProfile]] = None,
) -> ResolutionResult:
    """Resolve a company name/domain/industry into a proposed OrganizationProfile.

    Resolution order: registry → domain/alias → evidence graph → external
    enrichment (pluggable) → LLM classification (pluggable fallback).
    """
    cleaned_name = clean_company_name(company_name)
    domain = clean_domain(company_domain)
    path: list[str] = []

    # 1) Internal registry (name first, then domain)
    entry = lookup_by_name(cleaned_name) if cleaned_name else None
    if entry is None and domain:
        entry = lookup_by_domain(domain)
        if entry:
            path.append("registry:domain")
    elif entry:
        path.append("registry:name")

    if entry:
        profile = _profile_from_registry(entry, source="registry")
        profile.canonical_name = entry["canonical_name"]
        # confirm user-provided fields take precedence
        if industry:
            norm = normalize_industry(industry)
            if norm.mapped:
                _set_field(profile, "primary_industry", NormalizedValue(raw=industry, value=norm.canonical, source="user", confidence=0.95))
                _set_field(profile, "industry_subsector", NormalizedValue(raw=industry, value=norm.subsector or "", source="user", confidence=0.9))
        result = ResolutionResult(proposed=profile, confidence={}, resolution_path=path)
        result.confidence = {
            "overall": 0.9 if "registry" in path[0] else 0.5,
        }
        return result

    # 2) Domain/alias → evidence graph
    if session is not None:
        evidence = _evidence_match(session, cleaned_name)
        if evidence:
            path.append("evidence_graph:name")
            profile = OrganizationProfile(
                canonical_name=evidence["canonical_name"],
                organization_id=f"evidence-{evidence['canonical_name'].lower()}",
            )
            profile.source_provenance.append({"step": "evidence_graph", "source": "evidence"})
            if industry:
                norm = normalize_industry(industry)
                if norm.mapped:
                    _set_field(profile, "primary_industry", NormalizedValue(raw=industry, value=norm.canonical, source="taxonomy", confidence=norm.confidence))
                    _set_field(profile, "industry_subsector", NormalizedValue(raw=industry, value=norm.subsector or "", source="taxonomy", confidence=norm.confidence * 0.9))
                    reg = regulatory_intensity_for(norm.canonical)
                    if reg:
                        _set_field(profile, "regulatory_context", NormalizedValue(raw=industry, value=reg, source="taxonomy", method="inferred", confidence=0.6))
            return ResolutionResult(proposed=profile, resolution_path=path, confidence={"overall": 0.6})

    # 3) Industry-only input → taxonomy classification
    if industry and not cleaned_name:
        path.append("taxonomy:industry")
        profile = _profile_from_industry_text("", industry, domain)
        return ResolutionResult(proposed=profile, resolution_path=path, confidence={"overall": 0.7})

    # 4) External enrichment (pluggable)
    if enrich is not None:
        stub = _profile_from_industry_text(cleaned_name, industry, domain)
        enriched = enrich(stub)
        if enriched is not None:
            path.append("external_enrichment")
            return ResolutionResult(proposed=enriched, resolution_path=path, confidence={"overall": 0.5})

    # 5) LLM-assisted classification (pluggable fallback)
    if classify is not None:
        profile = classify(cleaned_name, industry)
        if profile is not None:
            path.append("llm_classification")
            return ResolutionResult(proposed=profile, resolution_path=path, confidence={"overall": 0.4})

    # Fallback: partial profile from whatever was provided
    path.append("partial")
    profile = _profile_from_industry_text(cleaned_name, industry, domain)
    return ResolutionResult(proposed=profile, resolution_path=path, confidence={"overall": 0.2})
