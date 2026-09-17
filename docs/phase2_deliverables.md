# Phase 2 Deliverables — Verified Brief Production Integration

**Date:** 2026-08-24
**Status:** IMPLEMENTED + TESTED LOCALLY. **NOT DEPLOYED** — awaiting approval.
**Constraint honored:** no deploy, no unrelated feature work.

---

## 1. Architecture changes

**New (engine):**
- `compass_collector/analysis/evidence_comparability.py` — the comparability
  dimension. Avoids the existing `comparability.py` collision.
  - `Comparability`: `unassessed` (default) | `direct_implementation` |
    `indirect_contextual` | `not_relevant`
  - `OutcomeAttribution`: `unassessed` | `explicit` | `uncertain` | `none`
  - `supports_direct_outcome_claim()` — fail-closed gate (direct + explicit only)
  - `attribution_limitation()` — human-readable limitation
  - Comparability is **never inferred**; unknown/empty → `unassessed`.
- `compass_collector/api/verified_router.py` — `GET /api/evidence/verified`.
- `compass_collector/data/verified/invoice_processing.json` — the **canonical**
  verified evidence set (7 records) with source + comparability + attribution.

**Removed (web):**
- `src/data/prototype/verified-invoice.ts` (hardcoded dataset) — deleted after
  parity confirmed.
- `src/__tests__/verified-evidence.test.ts` — integrity tests moved to the engine.

**Changed (web):**
- `src/app/verified-brief/page.tsx` — now a `force-dynamic` server component that
  fetches from the engine. No hardcoded copy; a graceful "unavailable" state if
  the engine is unreachable.

**Reused (not duplicated):**
- `evidence_mode.py` (P1 gate) and `verification_status` (source dimension)
  are untouched. No second verification pipeline.

## 2. Migration summary

- The 7 records were moved verbatim (ids preserved) from the web into the
  canonical engine JSON, with two new fields added by the Phase-1 audit:
  `comparability` and `outcome_attribution`.
- Phase-1 classifications preserved exactly: **0 direct, 5 indirect, 2 not
  relevant**; all `outcome_attribution = none`.
- Source-verification statuses preserved (`claim_verified`).
- Parity confirmed before deletion: same 7 ids, all fields present, summary
  matches (0/5/2).
- No DB migration required for Phase 2 (the JSON is the canonical store for the
  first category). A DB-backed store is a future step once the set grows.

## 3. API contract

`GET /api/evidence/verified?workflow=<slug>`

```jsonc
{
  "workflow": "invoice_processing",
  "category": "Finance",
  "problem": "Manual invoice processing",
  "recommendation": "Automated invoice capture with exception-based review",
  "reviewed_at": "2026-08-24",
  "available": true,
  "records": [{
    "id": "direct-insite-2010",
    "organization": "Direct Insite Corp.",
    "intervention": "...",
    "what_it_establishes": "...",
    "metrics": [{ "label": "...", "value": "...", "direction": "...", "passage": "..." }],
    "source": { "title": "...", "url": "https://www.sec.gov/...", "type": "SEC filing", "date": "2010-12-31" },
    "verification_status": "claim_verified",        // SOURCE dimension
    "comparability": "indirect_contextual",         // RELEVANCE dimension
    "outcome_attribution": "none",                  // ATTRIBUTION dimension
    "comparability_reason": "...",
    "selection_reason": "...",
    "supports_direct_outcome": false,               // fail-closed gate
    "attribution_limitation": "Indirect context only — does not document this intervention."
  }],
  "summary": {
    "total": 7, "direct_implementation": 0, "indirect_contextual": 5,
    "not_relevant": 2, "unassessed": 0, "supports_direct_outcome": 0
  }
}
```
- Missing `workflow` → 400. Unknown workflow → `available: false` (200).

## 4. Before-and-after brief comparison

| Aspect | Before Phase 2 | After Phase 2 |
|---|---|---|
| Data source | Hardcoded in Compass-Web | Canonical engine endpoint |
| Dimensions | Source verification + comparability (web model) | Source verification + comparability + **outcome attribution** (engine model) |
| Comparability values | 3 | 4 (+ `unassessed` default) |
| Fail-closed gate | Web-only | Engine `supports_direct_outcome_claim` |
| Rendering | Identical content | Identical content, now engine-served |
| Classifications | 0 direct / 5 indirect / 2 not relevant | **Unchanged** |

Rendered output is materially the same (evidence-gap notice, downgraded status,
per-record dual badges, contextual-impact table, reproducibility). The change is
**architectural**: the engine is now the canonical source and models attribution.

## 5. Test results

**Engine** — `443 passed`, 2 pre-existing failures (documented in
`docs/pre_existing_test_failures.md`; unrelated).
New: `tests/test_evidence_comparability.py` (11) and `tests/test_verified_data.py` (8):
- source verification and comparability are independent;
- `unassessed`/`indirect`/`not_relevant` fail closed;
- direct + uncertain/none attribution fails closed;
- endpoint returns 0/5/2 and `supports_direct_outcome: 0`;
- data integrity (trusted host, claim_verified, passages, no vendor sources).

**Web** — `226 passed`, `tsc` clean, `next build` clean (31 pages).
`/verified-brief` is dynamic and renders from the engine (verified locally:
evidence-gap notice, 0/5/2 summary, 19 sec.gov links).

## 6. Evidence acquisition candidate report

`docs/evidence_acquisition_report.md`:
- **0** primary-source, quantified invoice-automation **implementations** exist in
  the 54,277-record library.
- The only implementation records are **vendor case studies** (Cargill, Ricoh,
  Lamar, Nividous clients) — excluded by the bar, several anonymous.
- The 9 primary-source records are provider scale / adjacent (already indirect
  or not-relevant).
- **Data-integrity flag:** several vendor case studies carry
  `independently_verified = 1`; the flag is unreliable.
- Proposed targeted external acquisition (EDGAR full-text, gov audits,
  academic), with the per-candidate capture template and process rules.

## 7. Deployment risks

| Risk | Detail | Mitigation |
|---|---|---|
| Engine unreachable | `/verified-brief` now depends on the engine | Graceful "unavailable" state; no hardcoded fallback (by design) |
| JSON store not DB-backed | Canonical store is a file for one category | Acceptable for the first category; migrate when the set grows |
| `unassessed` default | New records fail closed until reviewed | Intended; review assigns comparability |
| `independently_verified` flag unreliable | Mis-set on vendor records | Do not use it as a verification signal; reconcile separately |
| Duplicate verification logic | Risk of re-deriving verification | Reused `evidence_mode.py`; no second pipeline |
| Web/engine divergence | — | Hardcoded web set removed; endpoint is canonical |

## 8. Not done (per instruction)

- No deployment.
- No evidence-library expansion (acquisition is a report + strategy, not an
  ingestion).
- No unrelated features.
