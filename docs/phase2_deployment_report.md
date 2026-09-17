# Phase 2 — Deployment Report

**Date:** 2026-08-24
**Result:** DEPLOYED — all predeployment and production smoke checks passed.

---

## 1. Predeployment verification

| Check | Result |
|---|---|
| Two pre-existing failures remain unrelated to Phase 2 | ✅ `test_sigterm_clean_shutdown` (timing-sensitive subprocess assertion) and `test_reclassify_migrates_legacy_tiers` (test isolation). Neither imports or touches any Phase 2 module; Phase 2 added only new files + 2 router lines in `app.py`. Documented in `docs/pre_existing_test_failures.md`. |
| Engine API returns the expected 7 records | ✅ |
| Record IDs preserved | ✅ `direct-insite-2010, checkfree-2001, checkfree-2002, heartland-q3-2011, paybox-2017, dover-supply-chain, rpm-map` |
| Source metadata / passages / verification status preserved | ✅ all `claim_verified`, all passages present, all sources on sec.gov |
| Comparability + attribution fields preserved | ✅ 0 direct / 5 indirect / 2 not relevant; all `outcome_attribution = none` |
| Web no longer depends on the deleted dataset | ✅ no references to `verified-invoice`; fetches the engine endpoint |
| API contract matches the web client | ✅ every field the client reads is present in the response |
| Verification/comparability thresholds unchanged | ✅ (no threshold changes) |

## 2. Deployment sequence (engine first)

1. **Compass-Engine** deployed first (`a567659`). Verified production endpoint before the web switch:
   `GET /api/evidence/verified?workflow=invoice_processing` → `available: true`, 7 records, summary 0/5/2.
2. **Compass-Web** deployed second (`c4edbc0`), after the engine endpoint was confirmed healthy.
3. **Failure behavior:** with the engine unreachable, the brief renders an explicit
   *"Verified evidence is currently unavailable … No cached or hardcoded copy is shown"*
   state. Verified locally against a dead engine port — no stale/unverified fallback.

## 3. Commit hashes

| Repo | Commit | Status |
|---|---|---|
| Compass-Engine | `a567659` | deployed, Online |
| Compass-Web | `c4edbc0` | deployed, Online |

CI: success on both pushes.

## 4. Endpoint response validation (production)

```
GET https://compass-engine-production-532b.up.railway.app/api/evidence/verified?workflow=invoice_processing
available: true
records: 7
summary: { total: 7, direct_implementation: 0, indirect_contextual: 5,
           not_relevant: 2, unassessed: 0, supports_direct_outcome: 0 }
sample: direct-insite-2010 | Direct Insite Corp. | claim_verified |
        indirect_contextual | attribution none | supports_direct_outcome false
all sources on sec.gov: true
```

## 5. Live UI verification (production)

| Check | Result |
|---|---|
| Verified brief renders | ✅ |
| Summary remains 0 direct / 5 indirect / 2 not relevant | ✅ |
| All source links resolve to their intended documents | ✅ 7/7 returned HTTP 200 |
| Evidence-gap notice visible | ✅ |
| No unsupported causal or quantitative claims | ✅ ("must not be read as expected results") |
| Exploratory / insufficient prototype modes still work | ✅ mode badge present |
| Named-company remediation still effective | ✅ no Finastra/Tetra Pak/"showed weaker results" |
| 5-section prototype brief intact | ✅ |

## 6. Test results

- **Engine:** 443 passed, 2 pre-existing failures (documented, unrelated).
  New: `test_evidence_comparability.py` (11), `test_verified_data.py` (8).
- **Web:** 226 passed, `tsc` clean, `next build` clean (31 pages).
- Production smoke tests: all passed (above).

## 7. Deviations / regressions

- **None.** No deviations from the approved plan; no regressions observed.
- Minor, expected: web test count moved 235 → 226 because the verified-evidence
  integrity tests moved from the web to the engine (`test_verified_data.py`).
- The web dataset file was deleted only after parity was confirmed.

## 8. Post-deploy state

- The verified brief is now **engine-served**; the web holds no evidence copy.
- Three independent dimensions are modeled and displayed: **source verification**,
  **comparability**, **outcome attribution**, with the fail-closed
  `supports_direct_outcome` gate.
- The honest evidence position is preserved: **no direct implementation evidence**
  for invoice automation.
