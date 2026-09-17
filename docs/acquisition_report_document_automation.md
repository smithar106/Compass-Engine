# Acquisition Report — Document / Process Automation Cohort

**Date:** 2026-08-24
**Workstream:** Plan A (targeted acquisition for the strongest category)
**Method:** EDGAR full-text search (`efts.sec.gov`) across 10-K/10-Q/8-K for
document/process/knowledge automation implementations with quantified outcomes;
each candidate fetched and read in context; passages verified verbatim.

---

## 1. Why this category

The category audit (`category_audit_report.md`) found **knowledge/document
processing automation** had the strongest seed and a coherent theme. This
acquisition confirms it and builds the first cohort of **direct implementation
evidence**.

## 2. Verified cohort (5 records, primary SEC sources)

### C1 — Exela / SourceHOV (document/knowledge automation) — STRONG
> "Revenue per head for SourceHOV has more than tripled ($18,000 per FTE in 2007
> to $56,000 per FTE in 2016) with headcount being reduced by over 1,000 FTEs
> **as a result of the adoption of its technology-focused strategy**."

- Source: `sec.gov/Archives/edgar/data/0001620179/000110465917040041/a17-15387_2ex99d1.htm`
- Outcome: revenue/FTE 3×; −1,000 FTEs · **Attribution: explicit**

### C2 — Ponce Financial (process automation + document workflow digitization) — STRONG
> "Our investment in Salesforce process automation and the digitization of our
> document workflows … We are beginning to see returns on these investments in
> the form of time-saving efficiencies, reduced costs of document storage,
> handling and destruction…"

- Source: `sec.gov/Archives/edgar/data/1874071/000095017025087092/pdlb-ex99_1.htm`
- Outcome: time-saving efficiencies; reduced document storage/handling costs · **Attribution: explicit**

### C3 — FVCBankcorp (RPA for reporting/process) — STRONG
> "Robotic process automation have reduced risk of error and reduced processing
> time from hours to minutes. Collectively hundreds of hours have been saved on
> daily, weekly, monthly and periodic repetitive manual processes."

- Source: `sec.gov/Archives/edgar/data/1675644/000167564424000082/microsofpowerpoint-2024a.htm`
- Outcome: processing time hours → minutes; hundreds of hours saved · **Attribution: explicit**

### C4 — BPO Management Services / Canadian Tire (document digitization) — STRONG
> "BPOMS implemented a document management system to scan and process all
> in-store credit card applications and other banking documents … Results:
> Faster approval of credit card and loan applications at a lower unit cost;
> Improved accuracy of data captured; Ability to retrieve and analyze captured
> data … Improved turnaround and customer service; Ability to deal with high
> business volumes during holiday seasons without having to staff to meet peak
> demand."

- Source: `sec.gov/Archives/edgar/data/1015920/000114420407008510/v066167_ex99-1.htm`
- Outcome: lower unit cost; faster approvals; improved accuracy; peak-volume
  handling without peak staffing · **Attribution: explicit** ("Results")

### C5 — TheRealReal (repetitive content/pricing automation) — STRONG (attribution partial)
> "We exited Q4 automating the pricing of 80% of unit volume, copywriting of 84%
> (including product title and description), and photo retouching of 85%."

- Source: `sec.gov/Archives/edgar/data/1573221/000156459021007159/real-ex992_6.htm`
- Outcome: 80–85% of unit volume automated · **Attribution: partial** (benefit
  expected, not yet reported)

## 3. Cohort summary

| # | Organization | Intervention | Outcome | Attribution |
|---|---|---|---|---|
| C1 | Exela / SourceHOV | Document/knowledge automation | Revenue/FTE 3×; −1,000 FTEs | Explicit |
| C2 | Ponce Financial | Process + document workflow automation | Time savings; lower document costs | Explicit |
| C3 | FVCBankcorp | RPA (reporting/process) | Processing hours → minutes | Explicit |
| C4 | BPO Mgmt / Canadian Tire | Document digitization | Lower unit cost; faster approvals | Explicit |
| C5 | TheRealReal | Repetitive content/pricing automation | 80–85% automated | Partial |

**5 of a 5–10 target cohort — minimum met.** All primary-source (SEC), with
quantified outcomes and verbatim passages. 4 have explicit attribution; C5 partial.

**Additional moderate candidates (not counted):**
- State Street — Beacon digitization program; KPI *categories* (cost reduction,
  funds per FTE) rather than reported results.
- Computer Task Group — pilot outcomes (decreased cost, reduced resource demand)
  without quantities.
- Regions Financial — no quantified outcome.
- Flywire — product-benefit marketing.

**Excluded:** Mitek, Captiva, Document Sciences, American Reprographics,
Standard Register, SS&C — vendors describing products → context only.

## 4. Pipeline (repeatable)

1. EDGAR full-text query for intervention term(s) + outcome language (10-K/10-Q/8-K).
2. Fetch each candidate; extract sentences with an intervention term + outcome cue.
3. **Read in context** to confirm (a) own implementation and (b) attribution.
4. Record organization, intervention, source URL, passage, outcome, attribution, comparability.
5. Human review assigns comparability + attribution (never inferred).

## 5. Next steps

1. Load the cohort into the engine verified store for a **document/process
   automation** workflow.
2. Assign `comparability = direct_implementation` and the attribution status per
   record (C1–C4 explicit; C5 uncertain).
3. Re-present the brief for that category as **implementation-backed** — the
   first production brief supported by directly relevant evidence.

## 6. Caveats

- "Explicit attribution" = the source states the intervention produced the
  outcome; it does **not** establish rigorous causal identification.
- C5's attribution is partial; it should be marked `uncertain`, not `explicit`.
- All are US-listed filers; non-US/private implementations need other source classes.
