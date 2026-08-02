# Organization Resolution — Prepared Plan (design only, not implemented)

Item 5 of the follow-up. Four upgrades are *prepared* here and **not implemented**.
Priority: the internal evidence graph is the next resolution tier **before** any
external service.

## Priority 1 — Evidence-graph organization registry (next tier)

**Goal:** resolution step 3 ("existing evidence-graph organization") becomes a
first-class, indexed tier instead of the current linear scan.

Already present:
- `compass_collector/organization/registry.py::build_registry_from_evidence(session)`
  aggregates `organization_name` (+ raw industries) from `intervention_records`.

Planned implementation (not done):
- Build the registry once at engine startup (or lazily) into a dict keyed by
  `clean_company_name` (`profile.py::clean_company_name`), with a secondary map
  of domain-like org names → canonical.
- Wire it into `resolve_organization` **before** the curated registry's domain
  fallback and **after** the curated name lookup, returning the evidence-graph
  profile (with `source: "evidence_graph"` provenance and `confidence ~0.6`).
- Invalidate/rebuild when `organization_normalized` backfill runs.
- Deterministic; no new dependencies.

## Priority 2 — External company enrichment (pluggable)

**Goal:** fill employee band, geography, revenue, business model from a public
company-data source when internal resolution is partial.

Planned interface (not implemented):
- `resolve_organization(..., enrich=...)` already accepts an optional callable
  `(profile) -> profile`. The default stays `None` (off).
- A candidate implementation would query an external API (e.g. Clearbit/Crunchbase/
  a company-domain endpoint) keyed by canonical name or domain, map the response
  onto `OrganizationProfile.fields` with `source: "external"`, `method: "explicit"`
  (domain/employee/revenue) or `"inferred"`, and low-ish confidence where the
  external record is unverified.
- Guarded by a `COMPASS_ENRICHMENT_KEY`-style env var; failure degrades to the
  internal profile without erroring.

## Priority 3 — LLM organization classification fallback

**Goal:** when name/domain/industry cannot be resolved internally, classify a
free-text industry/company description into the canonical taxonomy via the LLM.

Planned interface (not implemented):
- `resolve_organization(..., classify=...)` already accepts an optional callable
  `(name, industry) -> profile`.
- The fallback would prompt the LLM to emit `{canonical_name, primary_industry,
  subsector, business_model, geography}` from the supplied text, using the
  existing `LLM_EXTRACTION_PROMPT` conventions and the taxonomy vocabulary, then
  validate the output against `taxonomy.CANONICAL_INDUSTRIES`.
- `source: "llm"`, `method: "inferred"`, `confidence ~0.4`; only used after the
  internal tiers miss.

## Priority 4 — Higher sparse-context weights

**Goal:** promote employee-size / geography / business-model / regulatory factors
from neutral to meaningful scoring **once coverage justifies it**.

Planned (not implemented):
- Re-raise `CONTEXT_FACTOR_WEIGHTS` in `analysis/context_retrieval.py` only after
  the coverage report (see `docs/organization_benchmark_enriched.md`) shows
  employee ≥ ~30% and geography ≥ ~30%.
- Gate on measured coverage (e.g. read `GET /api/evidence/coverage`), not on a
  hardcoded flag, so weights promote automatically and reversibly.
- Until then the coverage-aware "boost on match, neutral on missing" behavior
  stays.

## Sequencing

1. Refresh production DB (1,306) + backfill → enables evidence-graph registry to
   be built from real coverage.
2. Wire evidence-graph registry tier (Priority 1).
3. Wire context-aware retrieval into the live recommendation path (from the
   benchmark findings) and re-benchmark.
4. Only then consider Priority 2 (external) and Priority 3 (LLM) as fallbacks.
5. Promote sparse weights (Priority 4) when coverage thresholds are met.
