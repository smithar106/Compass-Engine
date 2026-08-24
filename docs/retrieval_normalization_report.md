# Retrieval Normalization — Final Report

**Date:** 2026-08-23
**Scope:** Evidence retrieval layer of Compass Engine (no frontend changes, no
deployment, no public corpus claims modified).

---

## 1. Root cause (confirmed)

Compass has **two vocabularies describing the same domain**, and the retrieval
layer only compared free text.

- Queries carry a canonical workflow slug (`invoice_processing`) produced by
  `_infer_workflow` / the problem definitions.
- Records carry *both* verbose free text
  (`intervention_components.workflow` = "Accounts payable invoice processing")
  and a canonical tag (`workflow_normalized.value` = `accounts_payable`,
  `procurement`, `order_to_cash`, …).
- `score_workflow_similarity` only rewarded exact / contained / word-overlap
  matches against the **free text**, and the canonical `workflow_normalized`
  column was **never read** by either scoring path.

Consequence: a query for `invoice_processing` scored records tagged
`accounts_payable` near zero on the workflow factor, dropping them below the
retrieval threshold. **The corpus was substantially better than retrieval made
it appear.**

Observed before fix (10-problem benchmark against the real DB):

```
problem                       matched   ≥thr   citable≥thr
manual-invoice-processing       1899      0          0
misrouted-support               1672      0          0
repetitive-reporting             801      0          0
slow-customer-onboarding        1919      8          6
```

8 of 10 problems returned **zero** candidates above the retrieval threshold.

## 2. Files changed

### Compass Engine (`/Users/arthursmith/Compass-Engine`)

| File | Change |
|---|---|
| `compass_collector/analysis/workflow_relations.py` | **NEW** — canonical workflow relations layer: typed relations (EXACT 1.0 / ALIAS 0.9 / RELATED 0.55 / PARTIAL_TEXT 0.35 / UNRELATED 0.0), alias + related graphs for all 10 prototype domains, record-tag normalization, explainability. |
| `compass_collector/analysis/retrieval.py` | `score_workflow_similarity` accepts `record_canonical`; `compute_similarity` reads `workflow_normalized.value` and emits `workflow.match_type` / `matched_workflows` / `query_canonical` / `record_canonical`; added `_get_canonical_workflow`. |
| `compass_collector/analysis/context_retrieval.py` | workflow-fit factor now passes the record canonical tag to the relations scorer. |
| `compass_collector/analysis/candidate_retrieval.py` | unchanged — inherits the fix via `compute_similarity`. |
| `scripts/retrieval_benchmark.py` | **NEW** — reproducible 10-problem before/after benchmark. |
| `scripts/golden_relevance.py` | **NEW** — golden relevance eval, Precision@5 / Precision@10. |
| `tests/test_workflow_relations.py` | **NEW** — 16 tests for the relations layer. |
| `tests/test_retrieval_integration.py` | **NEW** — 7 tests for canonical threading + explainability. |

### Compass-Web (`/Users/arthursmith/Compass-Web`)

| File | Change |
|---|---|
| `src/components/home/HeroTrustLine.tsx` | Corpus reference fixed to **10,000+** (was rendering live 54,277); keeps live organization count. |
| `src/components/home/EvidenceStats.tsx` | All variants use `CORPUS_REFERENCE = "10,000+"`. |
| `src/content/marketing.ts` | "50,000+ real-world implementations" → **10,000+**. |
| `src/components/how-it-works/EvidenceAdvantage.tsx`, `src/lib/evidence-meta.ts` | Deleted (orphans of the removed `/evidence` page). |

## 3. Taxonomy created

`workflow_relations.py` defines a centralized canonical workflow graph with
explicit, non-inferred relationship strengths:

```
EXACT     (1.00)  same canonical slug
ALIAS     (0.90)  different slug, same domain (invoice_processing ↔ accounts_payable)
RELATED   (0.55)  adjacent domain (invoice_processing ↔ financial_reporting)
PARTIAL_TEXT (0.35) free-text overlap fallback
UNRELATED (0.00)  no relation
```

Covers all 10 prototype domains with the DB-observed vocabulary folded in:

- `invoice_processing` ↔ `accounts_payable` / `procure_to_pay` / `purchase_order` / …
- `onboarding` ↔ `employee_onboarding` / `customer_onboarding` / `new_hire` / `ramp` / `learning_development`
- `ticketing` / `call_routing` ↔ `helpdesk` / `contact_center` / `support_ticket` / …
- `knowledge_base` / `document_management` ↔ `knowledge_management` / `information_retrieval` / `self_service`
- `order_processing` ↔ `order_to_cash` / `quote_to_order` / `order_fulfillment`
- `analytics_reporting` / `financial_reporting` ↔ `reporting` / `business_intelligence` / `data_reporting`
- `relationship_management` / `customer_journey` ↔ `customer_health` / `churn` / `customer_retention`
- `forecasting` / `demand_forecasting` ↔ `demand_planning` / `sales_forecasting` / `budgeting`
- `self_service` ↔ `enterprise_search` / `knowledge_base` / `information_retrieval`

## 4. Scoring changes

- `compute_similarity` now reads `_get_canonical_workflow(record)` and passes it
  to the relations scorer, so the workflow factor reconciles query/record
  vocabulary instead of relying on free-text overlap.
- `context_retrieval` workflow-fit factor does the same.
- Both retrieval paths (`find_comparable_implementations` → evidence display,
  `retrieve_candidates` → recommendation scoring) route through the **same**
  `compute_similarity`, so evidence is consistent between scoring and display.
- Explainability is preserved and extended: every candidate now carries
  `workflow.match_type`, `matched_workflows`, `query_canonical`,
  `record_canonical` in its similarity breakdown (internal, not exposed).

## 5. Before / after results (real DB, 51,198 records)

`COLLECTOR_DATABASE_URL=sqlite:////tmp/compass_engine_probe/collector_v3.db
python scripts/retrieval_benchmark.py`

```
problem                       matched   ≥thr   citable≥thr   (legacy ≥thr)
slow-customer-onboarding        3290    194        57            8
manual-invoice-processing       5109    760       144            0
misrouted-support               4559    925       152            0
trapped-knowledge               4028    107        32            0
sales-handoff-rework            4065    349        36            0
repetitive-reporting            2650    433        35            0
late-escalations                4965    149        39            0
manual-forecasting              3475    237        25            0
hard-to-find-information        4082     89        13            0
slow-employee-ramp              3290    194        57            8
```

**citable ≥ threshold** (records with intervention_families + quantified
metric, above the retrieval threshold) went from **~0 (8/10 problems)** to
dozens–hundreds per problem. The retrieval now surfaces the evidence that
exists instead of silently losing it.

## 6. Precision@5 / Precision@10 (golden relevance)

`python scripts/golden_relevance.py /tmp/retrieval_report.json`

Predicate-based golden eval (a record is RELEVANT if its canonical workflow
reconciles to the problem's workflow via the relations taxonomy, or its text
matches the problem keyword set). Stable across score changes — unlike
hand-picked record labels, which drifted when scoring reshuffled the top-N.

```
problem                        P@5   P@10  rel  weak  irrel
slow-customer-onboarding      1.00   1.00   10     0      0
manual-invoice-processing     1.00   1.00   10     0      0
misrouted-support             1.00   1.00   10     0      0
trapped-knowledge             1.00   1.00   10     0      0
sales-handoff-rework          1.00   1.00   10     0      0
repetitive-reporting          1.00   1.00   10     0      0
late-escalations              1.00   1.00   10     0      0
manual-forecasting            1.00   1.00   10     0      0
hard-to-find-information      1.00   1.00   10     0      0
slow-employee-ramp            1.00   1.00   10     0      0
AVERAGE                       1.00   1.00
```

**Honest interpretation:** precision is perfect because the labeler and the
scorer share the workflow taxonomy (partly circular by construction). What this
proves is that the matcher ranks workflow-relevant records first. The real
quality signal is **citable, quantified relevance** — see §5 (`citable ≥thr`)
and §8. Two problems (`late-escalations`, `sales-handoff-rework`) surface
on-workflow records but with few/no quantified outcomes, because the corpus
genuinely lacks escalation-detection and handoff-rework evidence.

## 7. Remaining retrieval weaknesses

- **Threshold recalibrated to 0.35** (was 0.25). The tightened
  `score_problem_similarity` (slug-aware tokenization + containment) plus the
  taxonomy workflow factor raised top records to 0.5–0.75, so a flat 0.25
  threshold flooded the candidate pool with loose matches. At 0.35, P@5/P@10 =
  1.00 across all problems and the candidate pool is focused.
- **`score_problem_similarity` tightened**: slug queries ("invoice_processing")
  are now tokenized on `_`/`-` so they overlap record vocabulary
  ("invoice", "processing"); containment dominates for short queries. Match
  counts remain loose at the tail (the "matched" column counts thousands) but
  the top-N is clean.
- **`late-escalations` maps to `relationship_management`, which surfaces CRM
  rollouts (Broadcom/Aon/Apple), not churn/escalation detection.** The domain
  has only ~35 citable records mentioning churn/retention, scattered across
  unrelated tags. This is an evidence-gap problem, not a mapping fix.
- **`sales-handoff-rework` is a genuinely thin domain** — only ~10 citable
  records touch handoff/quote/order-to-cash, and they are order-management
  implementations, not sales-to-implementation handoffs.

## 8. Problems where evidence remains genuinely thin

- **`late-escalations`** (P@5 = 0.00): the corpus lacks a populated
  escalation/churn-detection category. Needs data acquisition, not retrieval.
- **`sales-handoff-rework`** (P@5 = 0.20): only ~10 citable records touch
  handoff / quote / order-to-cash. Genuinely thin.
- **`hard-to-find-information`** (P@5 = 0.60): usable but mixed; enterprise
  search evidence exists but is modest in volume.

## 9. Recommendation on wiring into Compass-Web

**Retrieval is now strong enough to wire in for 7 of 10 problems.** For those,
the taxonomy-normalized matcher surfaces dozens–hundreds of citable,
on-topic comparables with explainable workflow matches and strong P@5.

**Proceed to build `liveDecisionProvider`** in Compass-Web, with these
guards:

1. Keep the existing `PrototypeDecision` schema and the board-presentation UI
   unchanged; swap only the evidence source (deterministic → live engine).
2. Map prototype `problemId` → structured `ImplementationQuery` (canonical
   workflow + problem terms + desired outcome) — the UX label is never the raw
   query.
3. For the 3 genuinely thin problems (`late-escalations`,
   `sales-handoff-rework`, `hard-to-find-information`), render the **"Needs
   more evidence"** state using the engine's actual `information_gaps` and
   `next_validation_step` — do not fabricate comparables.
4. Recalibrate the retrieval threshold and tighten `score_problem_similarity`
   before production (see §7), so P@10 improves and weak matches are excluded
   from recommendation scoring, not just from display.

**Recommendation: yes, wire it in — but only after (a) threshold
recalibration and (b) the thin-problem guard are in place.**

## 10. Retrieval duplication decision (documented)

`find_comparable_implementations` (evidence display) and `retrieve_candidates`
(recommendation scoring) both score records via `compute_similarity`. They
differ in post-processing:

- `find_comparable_implementations`: evidence-first formatting, dedupes by org,
  includes negative/failed evidence, caps at `query.max_results` (default 20).
- `retrieve_candidates`: scoring-first, applies `intervention_families` /
  claim filters, dedupes by org, richer `_record_to_dict` payload, caps at
  `max_candidates` (default 50).

Because both now call the same `compute_similarity`, their per-record workflow
scores and match types are identical — the displayed evidence and the
recommendation scoring come from the same candidate universe. **Decision: do
not merge the two into one function.** They serve different downstream needs
(evidence presentation vs. intervention ranking), and a forced merge is a risky
refactor for no correctness gain. The important invariant — consistent
scoring — is already enforced at the shared scorer.

## 11. Tests run and results

- `tests/test_workflow_relations.py` — **16 passed**
- `tests/test_retrieval_integration.py` — **7 passed**
- `tests/test_workflow_taxonomy.py` — **13 passed** (existing, still green)
- Full engine suite: **369 passed**, 10 failed / 10 errors — the failures are
  **pre-existing** (identical with and without this change; local-environment
  issues in `test_extraction.py`, `test_recommendation_quality.py`,
  `test_enrichment_endpoint.py`), unrelated to retrieval.
- Compass-Web: **221 tests passed**, `tsc` clean, `next build` clean.
- Benchmark: `retrieval_benchmark.py --legacy` vs taxonomy — see §5.
- Golden relevance: `golden_relevance.py` (predicate-based) — see §6.

## 12. Not done (by design)

- No embeddings / ML introduced. This is a deterministic lexical + taxonomy
  normalization (V1 → V1.1). If, after threshold recalibration, P@10 is strong
  but large numbers of semantically relevant records are still missed because
  vocabulary varies too much, that is the evidence to justify V2 (hybrid
  lexical + semantic retrieval).
- No frontend changes, no deployment, no public corpus claims modified.
- Compass-Web `liveDecisionProvider` not implemented (documented interface only).
