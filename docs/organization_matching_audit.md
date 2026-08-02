# Compass Organization & Industry Matching — Audit and Upgrade

Date: 2026-08-02 · Engine version: 3.1.0 · Normalization version: `org-v1`

## 1. Current data-coverage audit

Source: `data/collector_v3.db` (131 MB, 1,306 intervention records, 4,042 metrics,
1,940 documents).

| Field | Records populated | % | Notes |
|---|---|---|---|
| `organization_name` | 1,289 | 98.7% | 746 unique names; mixed legal suffixes ("Inc.", "Corp"), dupes |
| `organization_industry` | 1,278 | 97.9% | **417 unique raw values — severe fragmentation** |
| `organization_geography` | 0 | 0.0% | never populated (all `[]`) |
| `organization_employee_count` | 0 | 0.0% | never populated |
| `organization_employee_band` | 0 | 0.0% | never populated |
| `organization_revenue` / band | 0 | 0.0% | never populated |
| `organization_stage` | 0 | 0.0% | never populated |
| `organization_type` | 141 | 10.8% | mostly `company` / `government` |
| `problem_business_function` | 331 | 25.3% | sparse |
| `intervention_components.workflow` | 153 | 11.7% | v3 records only |

### Taxonomy fragmentation

417 distinct industry values collapse to far fewer canonical groups. Examples of
equivalent labels that are currently *different* raw strings:

- Financial Services cluster: `Financial Services`, `financial services`,
  `financial_services`, `Finance`, `Banking`, `Bank`, `Banking/Financial Services`,
  `Banking and Financial Services`, `FinTech`, `Financial Technology`, `Insurance`,
  `Insurance and Financial Services`, `Capital Markets / Financial Services`,
  `Wealth Management / Financial Services` — **10+ spellings for one sector**.
- Case variants: `healthcare`/`Healthcare`, `banking`/`Banking`, `Technology`/`technology`.
- Separator variants: `financial_services`/`Financial Services`/`financial services`.
- Compound slash labels: `Technology / Manufacturing (Supply Chain & Data Solutions)`,
  `Dairy / Food & Beverage / Agriculture`.
- Annotated labels: `Government (Ministerial Department of the United Kingdom)`.

### Current retrieval weights and comparison logic

`compass_collector/analysis/retrieval.py` `SIMILARITY_WEIGHTS`:
problem 0.35, workflow 0.25, intervention 0.15, industry 0.10, company_size 0.10,
outcome 0.05. Industry matching is raw substring/word overlap — `banking` vs
`financial_services` scores **0.0**. Company size never fires (no employee data).
No geography, subsector, business model, or regulatory dimension exists.

`compass_collector/config/scoring_weights.py` (recommendation scoring):
problem_alignment 0.30, organizational_similarity 0.20, goal_alignment 0.20,
evidence_strength 0.15, implementation_fit 0.10, outcome_consistency 0.05.
`organizational_similarity` is computed with no canonical org profile.

## 2. Canonical taxonomy and organization schema

New package `compass_collector/organization/`:

- **`taxonomy.py`** — controlled vocabularies:
  - 17 canonical industries (`financial_services`, `healthcare`, `technology`,
    `manufacturing`, `retail_consumer`, `energy_utilities`, `government`,
    `education`, `telecommunications`, `transportation_logistics`,
    `media_entertainment`, `professional_services`, `construction_realestate`,
    `agriculture`, `hospitality`, `nonprofit`, `pharmaceuticals`), each with subsectors;
  - business models, employee size bands, revenue bands, geography aliases,
    regulatory intensity (per-industry), operational functions, workflows.
  - Deterministic normalization: case/separator folding, parenthetical stripping,
    compound-label splitting, exact-alias map, keyword fallback.
- **`profile.py`** — `OrganizationProfile` with per-field provenance
  (`raw, value, source, method, confidence, version`) covering all Phase 2 fields,
  plus `resolve_organization` implementing the Phase 4 resolution order.
- **`registry.py`** — curated known-org registry (canonical name, aliases, domains,
  industry, subsector, business model, HQ, geographies) + evidence-graph builder.
- **`backfill.py`** — record normalization with provenance (Phase 3).
- **`models/organization.py`** — persisted `organization_profiles` table.
- **`models/intervention.py`** — added `organization_normalized` JSON column
  (auto-migrated on startup).

## 3. Backfill results

`scripts/backfill_organization.py` normalizes all 1,306 records into
`organization_normalized` (raw values preserved; weaker inferred values never
overwrite trusted explicit ones). Dry-run coverage on the production DB:

| Normalized field | Present | % | Source |
|---|---|---|---|
| `canonical_name` | 1,289 | 98.7% | cleaned legal-suffix name |
| `primary_industry` | 1,275 | 97.6% | taxonomy (explicit alias or keyword) |
| `regulatory_context` | 1,275 | 97.6% | derived from canonical industry |
| `operational_function` | 331 | 25.3% | structured only |
| `geography` | 15 | 1.1% | text inference (regex) |
| `employee_count` | 4 | 0.3% | text inference |

Unmapped industry values: **3** (all legitimate long-tail: diversified
conglomerates and `N/A (Cross-industry)`). Finance cluster: `Banking`,
`Finance`, `FinTech`, `Financial Services`, etc. all normalize to
`financial_services` with correct subsector.

Every field carries provenance, e.g.:
```json
"primary_industry": {"raw": "Retail", "value": "retail_consumer",
  "source": "taxonomy", "method": "explicit", "confidence": 1.0,
  "version": "org-v1", "subsector": "retail", "broader": "Retail & Consumer"}
```

## 4. Company-resolution endpoint

`POST /api/organizations/resolve` (body: `company_name`, `company_domain`,
`industry`) and `POST /api/organizations/resolve/confirm`.

Resolution order: 1) curated registry → 2) domain/alias match → 3) evidence-graph
organization → 4) external enrichment (pluggable, off by default) → 5) LLM
classification (pluggable fallback). Returns the proposed `OrganizationProfile`,
per-field confidence, `resolution_path`, and `fields_requiring_confirmation`.

Examples (deterministic):
- `company_name="Shopify"` → Shopify / technology / ecommerce (registry)
- `company_domain="shopify.com"` → Shopify (registry:domain)
- `industry="Banking"` → financial_services / banking (taxonomy)
- `company_name="Stripe"` → Stripe / financial_services / payments

## 5. Updated Analyze UX (engine side)

`POST /api/analyze` accepts `organization_name` / `organization_domain` /
`organization_industry`. The engine resolves the organization early, stores the
profile on the session, and returns a `organization` section with what Compass
understood (Organization, Industry, Subsector, Company size, Geography, Business
model, Regulatory context) plus confirmation-required flags. `ConfirmRequest`
accepts an edited `organization` payload. The resolved profile feeds industry,
geography, and size into the retrieval pipeline. Website UI wiring is the
remaining client-side step in the Compass AI Website repo.

## 6. Retrieval-factor comparison (before vs after)

New `compass_collector/analysis/context_retrieval.py` exposes **ten separate fit
factors**: problem, workflow, operational-function, industry-subsector,
broader-industry, organization-size, business-model, geography, regulatory,
technology-readiness — with a per-comparable breakdown.

Weights: workflow 0.22 + problem 0.24 (= 0.46) vs industry (subsector 0.10 +
broader 0.08 = 0.18). Cross-industry records are never excluded purely on industry.

`scripts/benchmark_organization.py` output (representative queries):

| Query | BEFORE (legacy) | AFTER (context) |
|---|---|---|
| Stripe / invoice_processing / finance | Cargill 0.04, Alight 0.04, Tetra Pak 0.03 | Guardian Life 0.41, JP Morgan 0.38, Digital insurance 0.38 |
| healthcare / ticketing / customer_support | TELUS 0.10, Omega Healthcare 0.10 | California Dept of Health 0.38, Adventist Health 0.34 |
| Shopify / cloud_migration / engineering | Abu Dhabi Housing 0.06, 8x8 0.04 | GoTo 0.50, Cisco 0.44, Amadeus 0.43 |

Legacy retrieval returns near-random results (scores ~0.03–0.10) because raw
industry strings fail to match. Context retrieval returns organizationally
appropriate evidence with meaningful, explainable factor scores.

## 7. Tests and benchmark results

`tests/test_organization.py` — 19 tests, all passing:

1. company names resolve to the correct organization
2. aliases and domains resolve correctly
3. ambiguous/partial resolutions are low-confidence
4. industry-only entry works
5. equivalent industry labels normalize consistently (Finance cluster)
6. workflow similarity outranks weak same-industry evidence
7. same-workflow + same-subsector records get a meaningful boost
8. user edits override inferred context (user industry overrides registry)
9. different company profiles materially change retrieved evidence/ranking
10. all inferred fields retain provenance and confidence
11. deterministic inputs produce deterministic profiles and matching

Engine suite (recommendation, scoring, implementation, export, organization):
116 tests passing — no regressions.

## 8. Fields still too sparse to use safely

| Field | Coverage | Action |
|---|---|---|
| `organization_employee_count` / band | 0.3% | Do **not** use for ranking yet; treat as neutral (no boost, no penalty). Requires an enrichment source (HR/business data) |
| `organization_geography` | 1.1% | Do not filter on geography; usable only as a tiebreaker |
| `organization_revenue_band` | 0% | Unusable — needs external data |
| `organization_stage` | 0% | Unusable |
| `business_model` | ~registry only | Neutral until evidence-graph enrichment populates it |
| `operational_function` | 25.3% | Usable but sparse — combine with workflow fit, don't require it |
| `technology_posture` | 0% | Placeholder only |

Recommendation: wire the enrichment agent (`compass_agent`) to backfill
employee/geography/business-model from source documents (LLM enrichment already
targets these fields), then promote those factors from neutral to scoring.
