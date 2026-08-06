# Evidence Gap Engine v2 — Spec

> **The question this system answers, every night:**
> *Which recommendations are weakest? Why? Exactly what evidence — which
> industries, workflows, company sizes, geographies, technologies — would make
> them defensible?*

Compass has crossed the volume inflection point (4,201 implementations; ~2,000
decision-grade). The bottleneck is no longer *how much evidence exists* but
*whether the evidence that exists is enough to defend a specific decision*.
The Evidence Gap Engine turns the library from passive ("what evidence
exists?") to self-improving ("what evidence is missing?"), and hands Discovery
a **shopping list** instead of a mandate to wander the internet.

---

## 1. Current state (what already exists)

| Piece | Where | Limitation |
|---|---|---|
| 2-D gap analysis | `compass_agent/gap_analysis.py` — per `(workflow, business_function)`: comparables volume, tier depth, field coverage → `gap_score × demand = expected_impact`, `estimated_records_needed`, `proposed_source_types` | Only workflow × function. No industry/size/geo/tech dimensions. Demand = curated dict + keyword heuristics, not measured |
| Campaign planner | `compass_agent/campaign.py` — picks top `expected_impact` gaps as active campaigns | Campaign = one workflow; discovery still runs **generic DDG queries** ("case study implementation results ROI") |
| Decision coverage | `compass_collector/api/coverage_router.py` — per-function/per-workflow excellent/good/developing/limited | Auth-gated; not consumed by the planner |
| Canonical knowledge layer | `organization/taxonomy.py` (industry/subsector/function/workflow), `organization/vendor_taxonomy.py` (vendors, technologies + families) — **branch `feat/canonical-vendor-technology`** | Backfill must run at scale first (org: 30.3% → 97.6% canonical industry; vendors/tech: new) |

**The core defect this spec fixes:** `evidence_ops.py` computes gaps, then
ignores them during discovery. The gap is a *campaign label*, not a *hunting
directive*.

---

## 2. Goal

A nightly, persisted **Evidence Gap Report** — a ranked shopping list where
each item states:

- **What decision is weak** (workflow × business function)
- **Why** (not enough comparables? no decision-grade depth? missing
  rollout/validation fields? zero vendor diversity?)
- **What exactly to hunt** (canonical industry, employee band, geography,
  technology family, vendor diversity target)
- **How many more records** (`estimated_records_needed`)
- **Where to look** (source-library priority + composed search terms)

Discovery then executes the list first, with generic search as fallback —
inverting today's order.

---

## 3. The gap model

### 3.1 Primary dimensions (drives prioritization)

`category = (workflow, business_function)` — the unit of a decision, unchanged
from v1. Coverage = the *high-quality set* per category.

```
coverage(category) = f(
    n_decision_grade_or_gold,        # volume of defensible evidence
    tier_mix,                        # gold / decision_grade / supporting ratio
    field_coverage,                  # rollout_strategy, success_criteria,
                                     # lessons_learned, implementation_pattern,
                                     # baseline, deployment status, timeframe
    diversity,                       # see 3.2
)
```

Gap = distance from coverage targets (v1 thresholds retained: ≥5 comparables,
≥1 gold, ≥3 decision-grade, ≥50% field coverage), multiplied by **demand**.

### 3.2 Diversity (the new dimension)

Defensibility ≠ volume. `19 implementations, 18 from UiPath` is weak evidence;
`19 implementations, 12 vendors, 9 industries, 7 countries` is strong. Per
category, compute (using canonical fields):

- `vendor_entropy` / top-1 vendor share (concentration flag if > 60%)
- `industry_count` (canonical industries represented)
- `tech_family_count` (canonical technology families represented)
- `geography_count`, `employee_band_count` (when present)

A concentration or thin-diversity category gets a **diversity gap** with a
target like *"add ≥3 distinct vendors outside {dominant vendor}"*.

### 3.3 Demand (measured, not curated)

Replace the static `DEFAULT_DEMAND` + keyword table with measured demand:

1. **Analyze/outcome query volume** — count `/api/analyze` and
   `/api/outcomes` requests per workflow (primary signal; logged server-side).
2. **Benchmark gaps** — `compass_agent/benchmark.py` scenario misses.
3. **Fallback** — the curated keyword demand, only for categories with zero
   measured demand, at a floor weight.

### 3.4 Data-availability constraint (must be honest)

Canonical **industry** and **workflow** will be ≥95% after backfill, but
**geography (1.1%)**, **employee count (0.3%)**, **operational function
(19.9%)** remain sparse. Rules:

- Gaps on sparse dimensions are expressed as *desired attributes*, not
  hard filters: *"prefer North America, 200–500 employees when found"*.
- The report tracks dimension coverage over time (weekly), so the engine can
  flag *"employee-size diversity is unknowable — 0.3% of records have it"*
  as an enrichment directive (feed to the Outcome Discovery Worker), not a
  discovery failure.

---

## 4. Output schema

```python
@dataclass
class EvidenceNeed:
    workflow: str
    business_function: str
    decision_coverage: str            # excellent|good|developing|limited|absent
    gap_score: float                  # 0 healthy → 1 critical
    demand: float                     # measured (analyze/benchmark) or keyword floor
    expected_impact: float            # gap × demand
    comparables: int
    decision_grade: int
    gold: int
    missing_fields: list[str]
    estimated_records_needed: int
    # NEW — the shopping list
    target_industries: list[str]      # canonical industry keys
    target_employee_bands: list[str]  # canonical bands, best-effort
    target_geographies: list[str]     # canonical geos, best-effort
    target_tech_families: list[str]   # canonical families to add or diversify
    vendor_diversity: dict            # {top_vendor, share, target}
    search_terms: list[str]           # composed, category-specific
    source_library_priority: list[str]  # library ids ranked for this need
```

Persisted nightly as `data/gaps/evidence_gap_report.json` (full) +
`data/gaps/shopping_list.json` (top-N actionable) — and served read-only via
`GET /api/evidence/gaps` (same auth as coverage).

---

## 5. Nightly pipeline

```
23:00  Evidence Gap Engine run (budget-gated, idempotent)
  │
  ├─ 1. LOAD  canonical fields (org_normalized, vendors/software normalized,
  │            tiers, metrics)  ── via the records-read path
  ├─ 2. SCORE gaps per category (3.1) + diversity (3.2) + demand (3.3)
  ├─ 3. COMPOSE shopping list: per top-N gaps, generate search terms and
  │        source-library ranking
  ├─ 4. PERSIST report + shopping list; update dimension-coverage log
  ├─ 5. PUBLISH to planner: agent's next cycle reads shopping_list.json and
  │        runs its top item FIRST (discovery directives), DDG fallback only
  │        if the list is empty
  └─ 6. MEASURE: record gap deltas (before/after) for the cycle; report
          closure rate weekly
```

**Trigger:** agent daemon cycle start (before discovery) + explicit CLI
(`compass_agent` command) + scheduled job. Cooldown per category (e.g. 24h)
so a hunt has time to land before re-scoring.

---

## 6. Discovery integration (the inversion)

Today (`evidence_ops.py`): `analyze_gaps` → pick campaign → **DDG 130 generic
queries first** → libraries second.

After: `EvidenceGapEngine.report()` → pick top need → **compose targeted
queries** (`"{workflow} automation {industry} case study {outcome metric}"` +
vendor-diversity terms) and **targeted library** (`prioritize_libraries` scored
by `estimated_quality × relevance-to-need`, not cost alone) → DDG generic
search only as fallback when the shopping list yields nothing.

Per-need query templates (deterministic, seeded with measured terms):

- comparables hunt: `"{workflow} {business_function} implementation {industry}"`
- gold hunt: `"{workflow} automation results quantified {metric}"`
- diversity hunt: `"{workflow} {vendor_not_in_set}"`, `"{workflow} {tech_family}"`
- field hunt: `"{workflow} rollout strategy lessons learned"`

---

## 7. Metrics (replace "total implementations")

| Metric | Definition | North star |
|---|---|---|
| **Decision Coverage** | % of demand-weighted categories at `good`+ coverage | Finance 87%, Operations 94%, Legal 52%, HR 63% |
| **Gap closure rate** | categories moving up a coverage level / month | ≥ 20%/mo |
| **Implementation Diversity** | per category: vendors, industries, tech families, countries | ≥ 5 vendors & ≥ 4 industries per high-traffic category |
| **Shopping-list hit rate** | % of hunted items that produce an accepted record | ≥ 25% |
| **Dimension coverage** | % of records with canonical geo/size/function | 100% (backfill + enrichment) |

Stop reporting raw total. Keep it internal.

---

## 8. Implementation plan

| Phase | Work | Files |
|---|---|---|
| **0 (done)** | Canonical vendors/technologies + hardened org backfill | `vendor_taxonomy.py`, `backfill.py`, branch `feat/canonical-vendor-technology` |
| **1** | Run org + vendor/tech backfill on production; verify coverage endpoint (canonical_industry ≈ 97%) | — |
| **2** | Gap model v2: add diversity + measured demand + sparse-dimension rules to `analyze_gaps` | `gap_analysis.py` (extend), new `evidence_gap.py` engine module |
| **3** | Nightly report + shopping list persistence + `GET /api/evidence/gaps` | `data/gaps/`, `coverage_router.py` or new router |
| **4** | Discovery inversion: planner consumes shopping list first, composed queries + need-scored libraries | `evidence_ops.py`, `campaign.py`, `libraries.py` (`prioritize_libraries` relevance scoring) |
| **5** | Demand telemetry: log analyze/outcome queries per workflow | `analyze_router.py`, `outcome_router.py` |
| **6** | Enrichment feedback: sparse dimensions → Outcome Discovery Worker campaign | `outcome_discovery.py` |

**Tests:** pure scoring determinism (extend `tests/test_scoring_ranking.py`
pattern), shopping-list composition, query templates, diversity flags,
planner consumption order (shopping list before DDG).

---

## 9. Risks & guardrails

- **Sparse dimensions must not distort priority** — diversity/geo/size only
  *prefer* attributes; hard targets only on workflow/industry where coverage
  is real.
- **Query drift** — templates are deterministic + versioned; no LLM in the
  loop for gap *scoring* (pure math), LLM only for optional enrichment.
- **Budget** — shopping-list hunts are budget-gated like today; cooldowns
  prevent burning budget on unrecoverable categories.
- **Do not re-crawl** — shopping list reuses the claimed/processed page
  registry (`store.claim_library_page` / dedup) so hunts never repeat work.

---

## 10. Definition of done

- Every night the engine answers: *weakest decisions, why, and exactly what to
  hunt* — persisted and consumable by the planner.
- Discovery runs shopping-list-first; generic search is fallback.
- Decision Coverage (per business function) is the headline KPI.
- One executive trusts a recommendation enough to approve the project — and
  the gap report is what made the evidence defensible.

---

## 11. Implementation status

| Phase | Status | Notes |
|---|---|---|
| 0 — Canonical vendors/technologies + hardened org backfill | **done** (branch `feat/canonical-vendor-technology`) | vendors 316→58, tech 280→72; canonical industry 30.3%→97.6% on snapshot |
| 0b — Workflow canonicalization + inference | **done** (`organization/workflow_taxonomy.py`, `scripts/backfill_workflow.py`) | free-text workflows → canonical `ALL_WORKFLOWS` slugs; records without a stored workflow get one inferred from title/problem text (earliest-keyword-wins). Snapshot: 141 stored → 719 mapped (55.1%), 68 canonical slugs |
| 0c — LLM workflow recovery | **done** (`compass_agent/workflow_recovery.py`, `scripts/workflow_recovery.py`) | recovers the primary workflow from the **document body** for records deterministic inference can't classify (generic vendor-blog titles); recovered phrases mapped onto the canonical taxonomy, unmapped phrases returned as taxonomy candidates for table extension. Budget-gated, idempotent, dry-run, injectable LLM for tests (12 tests) |
| 2 — Gap model v2 | **done** (`compass_agent/evidence_gap.py`, CLI `gaps`) | multi-dimensional needs, diversity/concentration flags, measured-demand override, sparse-dimension preferences, composed search terms, library priority |
| 3 — Nightly report + persistence | **done** | `--write` → `data/gaps/`; **`GET /api/evidence/gaps`** endpoint added to `coverage_router.py` (same auth as coverage) |
| 4 — Discovery inversion | not started | planner consumes shopping list first |
| 5 — Demand telemetry | not started | analyze/outcome query logging |
| 6 — Enrichment feedback | not started | sparse dims → Outcome Discovery Worker |

**Findings from the first production-shape run (on the 1,306-record snapshot):**

1. **Workflow coverage is the critical data-quality lever.** 975/1,306 records
   (75%) carry no `intervention_components.workflow` and collapse into
   `uncategorized` — the decision-coverage KPI reads 0–1% on this snapshot
   because categories are singletons. Production reports 78.2% workflow
   coverage, so the engine must run against production (or a workflow-backfilled
   DB) to produce a meaningful KPI. **Workflow canonicalization/backfill is
   the next priority after org+vendor/tech backfills.**
2. **Business-function labels were messy** ("Supply Chain Management",
   "customer_support, marketing, operations") — `normalize_operational_function`
   in `taxonomy.py` now collapses them onto the canonical set (multi-label and
   slash values reduce to their first element; alias table extended).
3. **Sparse dimensions degrade gracefully** — geography/employee-band gaps are
   expressed as *preferences* + `data_limited_fields` flags, not hard filters.

**Workflow backfill results (same snapshot, after Phase 0b):**

- 141 stored free-text workflows → 719 records mapped (55.1%) onto 68 canonical
  slugs; 718 records got a workflow inferred from title/problem text.
- **The decision-coverage KPI became meaningful overnight**: finance 53%, IT
  57%, legal 43%, supply_chain 50%, customer_support 33%, engineering 32% —
  vs 0–1% before. Categories: 158 → 119.
- Remaining unmapped (~590 records) are mostly generic vendor-blog titles with
  no workflow signal in title/problem text — these need body-level extraction
  (LLM enrichment) rather than deterministic inference.
- Catch: keyword matching must use word stems, not full words
  ("invoic" matches invoice/invoicing/invoiced; "invoice" does not match
  "invoicing").


