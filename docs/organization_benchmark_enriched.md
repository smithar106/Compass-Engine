# Organization-Context Benchmark & Enrichment Metrics (against live production)

Date: 2026-08-02 · Engine: `compass-engine-production-532b.up.railway.app` · Agent: `Compass-Evidence-Agent`

## 0. Critical context — two caveats that frame every number below

1. **The production engine evidence DB is stale.** The live DB has **153 records**
   (the v3 curated subset), while the repo's `collector_v3.db` (git-lfs main) has
   **1,306 records**. The engine's startup only downloads the DB when the file is
   missing, so its Railway volume never picked up the expanded graph. The website
   has been recommending against 153 records.
2. **The engine still uses legacy retrieval.** `run_recommendation` →
   `retrieve_candidates` → `compute_similarity` (legacy weights: problem 0.35,
   workflow 0.25, industry 0.10, company_size 0.10). The new context-aware
   ten-factor retrieval (`analysis/context_retrieval.py`) is implemented and
   tested but **not yet wired into the live recommendation path**, so the live
   API cannot report per-factor breakdowns yet.

## 1. Field coverage (live enriched DB, `GET /api/evidence/coverage`)

| Field | n / total | % | Note |
|---|---|---|---|
| organization_name | 151 / 153 | 98.7% | |
| **raw industry values (unique)** | **130** | — | still fragmented in prod (417 across the full 1,306 DB) |
| canonical_industry (org_normalized) | 0 / 153 | 0.0% | **backfill not applied to production DB** |
| industry_subsector | 0 / 153 | 0.0% | backfill not applied |
| employee_count | 2 / 153 | 1.3% | agent-enriched (was 0%) |
| employee_band | 2 / 153 | 1.3% | agent-enriched |
| geography | 4 / 153 | 2.6% | agent-enriched (was 0%) |
| operational_function | 141 / 153 | 92.2% | v3 subset is densely tagged |
| workflow | 147 / 153 | 96.1% | v3 subset |
| **agent_enriched records** | **10** | — | published to engine over HTTP |

**Before/after enrichment** (sparse fields): employee 0% → 1.3%, geography 0% → 2.6%
after the agent's first ~29 attempts (10 validated). Still far below a usable
threshold — do **not** raise sparse-factor weights yet (see §5).

## 2. Retrieval changes for the same problem across four organization profiles

Problem: manual invoice processing (finance), same workflow + problem text.

| Profile | Top category | Confidence | Comparables | Risks |
|---|---|---|---|---|
| No org (baseline) | Workflow_Automation | 0.60 (moderate) | Alight, Tetra Pak, Merck | Mixed outcomes; exception paths |
| Stripe (fintech) | Workflow_Automation | 0.60 | Alight, Tetra Pak, Merck | same |
| Walmart (retail) | **Software** | **0.62 (moderate)** | **Accent Group, Shopify, Breville** | **System integration complexity** |
| Hospital (healthcare) | Workflow_Automation | 0.62 | **Alight, Omega Healthcare, AmerisourceBergen** | Mixed outcomes |

**Company context effect (vs baseline):**
- Stripe (fintech): top **same**, comparables **same**, risks **same**
- Walmart (retail): top **CHANGED** (Workflow_Automation → Software), comparables **CHANGED**, risks **CHANGED**
- Hospital (healthcare): top **same**, comparables **CHANGED**, risks **same**

So organization context materially changes evidence + ranking for some profiles
(retail most strongly), and leaves others unchanged — consistent with the design
intent that context *nudges* rather than dominates.

**Workflow vs industry dominance:** the live engine reports legacy-similarity
ranking (problem 0.35 + workflow 0.25 > industry 0.10 + size 0.10), so workflow
+ problem still dominate broad industry in production. The new ten-factor
breakdown is verified by unit tests (`test_organization.py`) but is not live.

## 3. Live enrichment metrics (agent store, via `railway ssh`)

| Metric | Value |
|---|---|
| attempted records | 29 |
| valid enrichments | 10 |
| invalid enrichments | 19 |
| **rejection rate** | **65.5%** |
| total cost | $0.02252 |
| cost per attempted record | $0.00078 |
| cost per valid enrichment | $0.00225 |
| cost per usable record | $0.00225 (= $0.02252 / 10; all publishes set richness=rich) |
| cost per rich record | $0.00225 |
| provenance accuracy | not measured (needs gold set) |
| overwrite conflicts | not measured (needs pre-image tracking) |
| benchmark impact | see `python -m compass_agent benchmark --dry-run` |

Rejection rate is high (65.5%) — the LLM returns `rejected`/insufficient for a
majority of candidate records. That is expected on this candidate set and is the
main lever for cost efficiency.

## 4. Budget spend (live)

Daily $0.02 / $0.50 (4%), total $0.02 / $3.75 (0.6%). No thresholds crossed yet;
budget-alert structured logs (`{"event":"budget_alert",...}` at 75/90/100% of
daily and total) are deployed and will fire as spend grows.

## 5. Recommendations (from benchmark evidence — no changes implemented)

1. **Refresh the production engine DB to the current 1,306-record graph** and
   apply the canonical backfill (`organization_normalized`). Without this, every
   coverage/retrieval number above is measured against a 153-record snapshot and
   the 417→canonical taxonomy work is invisible to production.
2. **Wire `analysis/context_retrieval.py` into the live recommendation path**
   (it is tested but unused), then re-run this benchmark to expose the ten-factor
   breakdown and verify workflow/problem dominance live.
3. **Do not raise sparse-factor weights yet.** Employee 1.3% / geography 2.6%
   coverage is far below a level where matching is meaningful; the coverage-aware
   neutral-on-missing behavior should remain.
4. **Throughput/budget:** with only 10 validated enrichments (< 50), do not
   change documents-per-cycle, daily budget, or concurrency. Re-assess after ≥ 50
   validated enrichments; the 65.5% rejection rate suggests candidate filtering
   (skip records the LLM flags `rejected` before claiming) is a cheaper lever
   than raising budget.
