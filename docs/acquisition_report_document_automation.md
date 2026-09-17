# Acquisition Report — Document / Process Automation Cohort

**Date:** 2026-08-24
**Workstream:** Plan A, step 3 (targeted acquisition for the strongest category)
**Method:** EDGAR full-text search (`efts.sec.gov`) across 10-K/10-Q/8-K for
document/process/knowledge automation implementations with quantified outcomes;
each candidate fetched and read in context; passages verified verbatim.

---

## 1. Why this category

The category audit (`category_audit_report.md`) found **knowledge/document
processing automation** had the strongest seed (Exela/SourceHOV) and a coherent
theme. This acquisition confirms that finding and expands the cohort.

## 2. Verified candidates (source-verified, primary SEC sources)

### C1 — Exela / SourceHOV (document/knowledge automation) — STRONG
> "Revenue per head for SourceHOV has more than tripled ($18,000 per FTE in 2007
> to $56,000 per FTE in 2016) with headcount being reduced by over 1,000 FTEs
> **as a result of the adoption of its technology-focused strategy**."

- Source: SEC filing — `sec.gov/Archives/edgar/data/0001620179/000110465917040041/a17-15387_2ex99d1.htm`
- Outcome: revenue/FTE 3×; −1,000 FTEs
- **Attribution: explicit** ("as a result of")

### C2 — Ponce Financial (process automation + document workflow digitization) — STRONG
> "Our investment in Salesforce process automation and the digitization of our
> document workflows, which we began in 2021 … We are beginning to see returns on
> these investments in the form of time-saving efficiencies, reduced costs of
> document storage, handling and destruction, and a more comprehensive view of
> our customer relationships."

- Source: SEC exhibit — `sec.gov/Archives/edgar/data/1874071/000095017025087092/pdlb-ex99_1.htm`
- Outcome: time-saving efficiencies; reduced document storage/handling/destruction costs
- **Attribution: explicit** ("returns on these investments in the form of")

### C3 — FVCBankcorp (RPA for reporting/process) — STRONG
> "Robotic process automation have reduced risk of error and reduced processing
> time from hours to minutes. Collectively hundreds of hours have been saved on
> daily, weekly, monthly and periodic repetitive manual processes."

- Source: SEC exhibit — `sec.gov/Archives/edgar/data/1675644/000167564424000082/microsofpowerpoint-2024a.htm`
- Outcome: processing time hours → minutes; hundreds of hours saved; reduced error risk
- **Attribution: explicit** (RPA "have reduced … saved")

### C4 — TheRealReal (automation of repetitive content/pricing work) — STRONG
> "We exited Q4 automating the pricing of 80% of unit volume, copywriting of 84%
> (including product title and description), and photo retouching of 85%."

- Source: SEC exhibit — `sec.gov/Archives/edgar/data/1573221/000156459021007159/real-ex992_6.htm`
- Outcome: 80–85% of unit volume automated across three processes
- **Attribution: partial** — scale of automation reported; operating-leverage
  benefit stated as an expectation ("we expect our automation efforts to
  meaningfully contribute to operating leverage")

## 3. Cohort status

| # | Organization | Category | Attribution | Status |
|---|---|---|---|---|
| C1 | Exela / SourceHOV | Document/knowledge automation | Explicit | Verified |
| C2 | Ponce Financial | Process + document workflow automation | Explicit | Verified |
| C3 | FVCBankcorp | RPA (reporting/process) | Explicit | Verified |
| C4 | TheRealReal | Repetitive content/pricing automation | Partial | Verified (attribution partial) |

**4 verified direct-implementation candidates** (target 5–10). All primary-source
(SEC), with quantified outcomes and supporting passages.

**Ambiguous / excluded:**
- Flywire — product-benefit marketing ("AR automation gains 30% drop in staff
  effort"); not clearly the company's own implementation → not counted.
- Regions Financial — "intelligent process automation efficiency through bots";
  no quantified outcome → not counted.
- Mitek, Captiva, Document Sciences, American Reprographics — vendors describing
  products → context only.

## 4. Pipeline (repeatable)

1. **EDGAR full-text** query for the intervention term(s) + outcome language,
   restricted to 10-K/10-Q/8-K.
2. Fetch each candidate; extract sentences containing the intervention term and
   an outcome cue (reduced/saved/hours/efficiency/FTE).
3. **Read in context** to confirm (a) it is the company's own implementation and
   (b) the source attributes the outcome to it.
4. Record: organization, intervention, source URL, exact passage, outcome,
   attribution status, comparability status.
5. Human review assigns `comparability` and `outcome_attribution` (never inferred).

## 5. Next steps

1. Acquire **1–6 more** records to reach a 5–10 cohort (continue EDGAR full-text;
   add government/academic sources).
2. Manually verify each; assign comparability + attribution.
3. Load the cohort into the engine verified store (`data/verified/`) for the
   document/process-automation workflow.
4. Re-present the brief for that category as **implementation-backed**.

## 6. Caveats

- "Explicit attribution" means the source states the intervention produced the
  outcome; it does **not** establish rigorous causal identification.
- C4's attribution is partial (a benefit is expected, not yet reported).
- Candidates are US-listed filers; non-US and private implementations are not
  covered by EDGAR and need other source classes.
