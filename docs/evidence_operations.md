# Implementation Intelligence Library — Design

> **The agent does not collect information because it exists. It collects
> information because a specific decision needs it.**

This is the governing principle. Every dollar spent on evidence acquisition is
tied to improving a Decision Brief — not to "collecting the web."

> Naming: this is the **Implementation Intelligence Library**, not an "evidence
> database." "Database" describes the storage technology; "Implementation
> Intelligence Library" describes the strategic asset — the thing investors,
> customers, and future employees will understand and value.

## The three systems

| System | Purpose | Status |
|---|---|---|
| **Implementation Intelligence Library** | The strategic asset: enrich existing records, discover new evidence from trusted Source Libraries, validate, and publish only implementation-rich records | this build |
| **Decision Engine** | Turns that intelligence into defensible recommendations | live (compass-engine) |
| **Implementation System** | Helps organizations execute and measure recommendations | live |

## The primary unit is a Source Library

Discovery no longer begins with "search the web." It begins with a **Source
Library** — one trusted collection of implementation evidence:

- Cloud vendors: AWS / Microsoft / Google / Oracle / SAP / Salesforce /
  ServiceNow / Snowflake / Databricks customer stories
- Consulting: Accenture / Deloitte / McKinsey / Bain / BCG / EY / KPMG / PwC
- Government: GAO / OECD / World Bank / NIST / NHS / US Digital Service /
  UK GDS / state audit offices
- Public companies: SEC filings, annual reports, earnings transcripts
- Academic, industry associations, conference proceedings, engineering
  retrospectives, customer presentations

Each library tracks: estimated quality, implementation richness, acceptance
rate, benchmark contribution, duplicate rate, average implementation fields,
cost per accepted record, cost per improved Decision Brief.

## Agent cycle (extended)

```
Inspect benchmark → identify weakest decision category → choose best source
libraries → discover → crawl → extract → validate → publish → benchmark →
measure Decision Brief improvement → repeat
```

Campaigns begin with benchmark gaps, map to target libraries (e.g. customer
onboarding missing rollout strategy/governance/validation gates → Microsoft,
Salesforce, ServiceNow, Accenture), and general web search is only a fallback.

## Library exploration

Each Source Library supports: `discover → crawl → extract → validate → publish →
metrics`. Progress is persisted (discovered / processed / accepted / rejected /
remaining pages) so the agent resumes where it stopped and never re-crawls the
same content.

## Prioritization

The planner ranks libraries to answer "what is the single highest-value evidence
campaign right now?" using: benchmark impact, implementation density, source
quality, organization/workflow diversity, cost, and acceptance rate. It prefers
campaigns that increase diversity, not just volume.

## Acquisition strategies

The planner chooses an acquisition strategy per Source Library (preferred +
fallback), and **learns which strategy performs best** for each library over
time (accepted records, cost per accepted):

- **FetchFox browser automation** — the primary strategy for JavaScript-heavy /
  interactive / paginated customer-story libraries (AWS, Microsoft, Google,
  Salesforce, ServiceNow, Snowflake, Databricks). A generated FetchFox workflow
  crawls the library and extracts implementation evidence directly from each
  customer story. Never used for broad web search.
- **Static crawler** — the existing HTTP + index-expansion crawler; the general
  fallback.
- **OpenCLI browser** — used when a browser-bridge profile is connected.
- **Direct API** — for libraries with a JSON/API endpoint (e.g. SEC EDGAR).
- **RSS** — for blogs/feeds (e.g. UK GDS blog).
- **General web search** — last-resort fallback for a campaign.

## Publish gate

A discovered record is **accepted** only if: no near-duplicate exists, schema +
provenance validation passes, and it is expected to improve the category
benchmark (valid tier + required fields + implementation depth). Otherwise it is
rejected and counted in library/campaign metrics.

## Success metrics

Report (not "pages crawled"): implementation records, implementation-rich
records, accepted records, organizations/industries covered, decision categories
improved, Decision Briefs improved, production-ready decisions, cost per
accepted record, cost per improved Decision Brief, cost per implementation-rich
record.

## Long-term objective

Compass becomes the world's best implementation intelligence library. Every
month the library grows larger, better, more diverse, more defensible, and more
useful. The success criterion is not collecting more documents — it is producing
better Executive Decision Briefs than any consultant, AI system, or internal
team could produce. Architectural target: **50,000** high-quality,
implementation-rich records across industries and workflows — a scale where
Compass competes not with consultants on individual projects, but with something
no consulting firm has: a continuously expanding, structured implementation
intelligence library that gets better every day. (Path: 5,000 → 10,000 → 50,000.)

