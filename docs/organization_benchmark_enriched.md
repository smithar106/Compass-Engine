# Organization-Context Benchmark & Enrichment Metrics (against live production)

Date: 2026-08-02 (second pass, post-DB-refresh + context-retrieval wiring) · Engine: `compass-engine-production-532b.up.railway.app` · Agent: `Compass-Evidence-Agent`

## 0. State of the production pipeline (updated)

- **Production DB refreshed**: the engine's Railway volume now serves the full
  **1,306-record** graph (was a stale 4 MB / 153-record snapshot) with the
  canonical backfill applied (`organization_normalized`, 97.6% canonical
  industry, 100% normalized).
- **Context-aware retrieval is live**: `retrieve_candidates` now uses the
  ten-factor context retrieval and `component_scoring` uses canonical industry
  matching, so `Banking`/`FinTech`/`Financial Services` match and comparables
  reflect organization context.

## 1. Field coverage (live enriched DB, `GET /api/evidence/coverage`)

| Field | n / total | % | Note |
|---|---|---|---|
| organization_name | 1,289 / 1,306 | 98.7% | |
| **raw industry values (unique)** | **417** | — | fragmented pre-taxonomy |
| canonical_industry (org_normalized) | 1,275 / 1,306 | 97.6% | backfill applied |
| industry_subsector | 1,275 / 1,306 | 97.6% | backfill applied |
| employee_count | 0 / 1,306 | 0.0% | agent will backfill going forward |
| employee_band | 0 / 1,306 | 0.0% | |
| geography | 0 / 1,306 | 0.0% | |
| operational_function | 331 / 1,306 | 25.3% | |
| workflow | 141 / 1,306 | 10.8% | |
| **agent_enriched records** | **0** | — | the DB refresh reset prior enrichments; agent re-accumulates |

Top canonical industries: technology 223, healthcare 186, manufacturing 183,
financial_services 169, retail_consumer 95, professional_services 68, government 64.

## 2. Retrieval changes for the same problem across four organization profiles

Problem: manual invoice processing (finance), same workflow + problem text.

| Profile | Top category | Confidence | Comparables | Risks |
|---|---|---|---|---|
| No org (baseline) | Workflow_Automation | 0.60 | Alight, Tetra Pak, Merck | Mixed outcomes; exception paths |
| Stripe (fintech) | Workflow_Automation | 0.60 | Alight, Tetra Pak, Merck | same |
| Walmart (retail) | **Software** | 0.65 | **Accent Group, American Furniture Warehouse, Shopify** | Mixed outcomes; integration complexity |
| Hospital (healthcare) | **Software** | 0.60 | **CA Dept of Health Care Services, TELUS, AmerisourceBergen** | Mixed outcomes; integration complexity |

**Company context effect (vs baseline):**
- Stripe (fintech): top **same**, comparables **same**, risks **same** — fintech
  has thin invoice-processing evidence, so context does not override evidence
- Walmart (retail): top **CHANGED**, comparables **CHANGED** (now retail orgs),
  risks **CHANGED**
- Hospital (healthcare): top **CHANGED**, comparables **CHANGED** (now healthcare
  orgs), risks **CHANGED**

The canonical taxonomy + context retrieval now surface organizationally relevant
comparables (retail → furniture/retail orgs, healthcare → health orgs) instead of
unrelated matches.

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

## 4. Budget spend (live)

Daily $0.02 / $0.50 (4%), total $0.02 / $3.75 (0.6%). Budget-alert structured
logs (`{"event":"budget_alert",...}` at 75/90/100% of daily and total) are live.

## 5. Recommendations (from benchmark evidence)

1. Keep **sparse-factor weights neutral** until the agent re-accumulates employee
   (0%) and geography (0%) coverage on the refreshed DB.
2. **No throughput/budget change** until ≥ 50 validated enrichments; the 65.5%
   rejection rate suggests candidate pre-filtering as the cheaper lever.
3. Next: wire the evidence-graph organization registry tier (Priority 1 in
   `docs/organization_resolution_plan.md`), then external/LLM fallbacks.

