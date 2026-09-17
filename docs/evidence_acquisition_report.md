# Evidence Acquisition Candidate Report — Invoice Automation

**Date:** 2026-08-24
**Scope:** the existing 54,277-record library (`collector_v3.db`)
**Question:** are there records documenting actual invoice-automation
implementations suitable for manual verification?

---

## 1. Method

Searched `intervention_records` for the target intervention classes:
automated invoice capture, accounts payable automation, intelligent document
processing, invoice exception handling, invoice-to-payment workflow automation.
For each match, checked for a linked document, a quantified outcome metric, and
a primary/independent source type.

## 2. Findings

| Measure | Count |
|---|---|
| Invoice-related records (title/problem/description/workflow) | 940 |
| …with a linked document | 764 |
| …with a **primary** source type (SEC / gov / academic) | 9 |
| …primary **and** a quantified metric | 8 |
| Records matching invoice/AP **automation** terms | 255 |
| …automation terms **and** document **and** quantified metric | **3** |
| …of those, primary-source | **0** (all 3 are vendor case studies) |

### The 9 primary-source records are provider-scale / adjacent — not implementations

They are the same records already in the verified brief (Heartland, Waystar,
CheckFree ×3, Direct Insite ×3). They document the **provider's own** platform
scale or adjacent programs, not a customer implementing invoice automation with
an attributable outcome. (See `Compass-Web/docs/verified-brief-comparability-audit.md`.)

### The closest "implementation" records are vendor case studies (excluded by the bar)

| Organization | Intervention | Metric | Source |
|---|---|---|---|
| Cargill | RPA + OCR intelligent automation | $19M cumulative savings; 236 automations | automationanywhere.com |
| Ricoh | Intelligent automation deployment | €100k/month; €1.09M total | automationanywhere.com |
| Lamar Advertising | Automated invoice processing (Oracle Fusion) | Processing time manual → automated | oracle.com |
| Nividous clients (several, largely anonymous) | Invoice/claims/payment automation | 30–83% TAT/effort reductions | nividous.com |

These describe **actual implementations** — but every one is **vendor-reported**
and/or **anonymous**, so they do not meet the verified bar (primary,
identifiable organization, attributable outcome).

### Data-integrity flag

Several vendor case studies carry `independently_verified = 1` in the DB even
though their source is the vendor's own marketing site. The
`independently_verified` flag is therefore **not reliable** and must not be
treated as satisfying source verification. This should be reconciled.

## 3. Conclusion (explicit)

**The existing corpus contains no suitable candidates for verified
direct-implementation evidence for invoice automation.**

- 0 primary-source, quantified invoice-automation **implementations**.
- The only implementation records are vendor case studies (excluded) and largely
  anonymous.
- The primary-source records are provider scale / adjacent, already classified
  `indirect_contextual`/`not_relevant`.

## 4. Proposed targeted external-source acquisition strategy

Acquire records that satisfy the bar: a primary source, an identifiable
organization, a specific invoice-automation intervention, and an attributable
outcome.

**Sources to target (primary / independent):**
1. **SEC EDGAR full-text search** — 10-K/10-Q/8-K disclosures naming AP/invoice
   automation programs with quantified outcomes (e.g. "accounts payable
   automation reduced …"). Full-text search endpoint:
   `efts.sec.gov/LATEST/search-index?q=...`.
2. **Government audits / oversight** — GAO, state auditors, NHS, gov.uk
   published efficiency reviews citing invoice/AP automation outcomes.
3. **Peer-reviewed / academic** — controlled studies of AP automation with
   measured results.
4. **Public-company earnings calls** — operator statements quantifying AP/invoice
   automation results (with named companies).

**Per-candidate capture template:**
organization · intervention · source URL + document · exact supporting passage ·
baseline · observed outcome · measurement period · attribution limitations ·
verification status · comparability status.

**Process rules (unchanged):**
- Human review assigns `comparability` and `outcome_attribution`; no automatic
  promotion from keyword similarity, industry, or source verification.
- Vendor case studies may be **context**, never verified direct implementation
  evidence, unless corroborated by an independent primary source.
- Target: 5–10 verified **direct implementation** records for invoice
  automation before re-presenting the brief as implementation-backed.

**Realistic expectation:** primary-source, attributable invoice-automation
implementations are rare (companies seldom disclose specific AP-automation
outcomes). Acquisition may require a targeted EDGAR full-text campaign and a
lower bound on what "attributable" means — which must be decided by review, not
inferred.
