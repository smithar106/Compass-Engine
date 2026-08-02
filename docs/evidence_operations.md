# Evidence Operations — Design

> **The agent does not collect information because it exists. It collects
> information because a specific decision needs it.**

This is the governing principle. Every dollar spent on evidence acquisition is
tied to improving a Decision Brief — not to "collecting the web."

## The three systems

| System | Purpose | Status |
|---|---|---|
| **Evidence Operations** | Continuously improves the implementation intelligence: inspect gaps, plan targeted campaigns, discover/fetch/extract/publish only what a decision needs | this build |
| **Decision Engine** | Turns that intelligence into defensible recommendations | live (compass-engine) |
| **Implementation System** | Helps organizations execute and measure recommendations | live (implementations/workspaces) |

## Agent cycle (extended)

The existing enrichment cycle is preserved. The new cycle is:

```
Inspect → Plan → Discover → Collect → Extract → Enrich → Validate → Publish → Benchmark → Learn
```

1. **Inspect** — `gap_analysis`: measure evidence gaps per decision category
   (workflow × business function × intervention). Rank by *expected impact* =
   decision demand × gap severity (sparse comparables, missing rollout strategy /
   validation gates / lessons, low gold/silver coverage).
2. **Plan** — `CampaignPlanner`: pick the highest-impact categories, estimate
   evidence needed (records + gold tier), propose high-value source types,
   persist a `Campaign` with status/cost/benchmark-delta tracking.
3. **Discover** — reuse the existing Compass collection framework
   (`scraper/search/query_generator.py`, `scraper/sources/web_search.py`,
   `config/evidence_seeds.yaml`, source registry). No second crawler.
4. **Collect** — claim candidates; fetch (HTTP / existing crawl engine) + parse
   (docling/bs4) to plain text.
5. **Extract** — LLM extraction (budget-gated, shared DeepSeek budget) into the
   canonical evidence schema.
6. **Enrich** — the existing enrichment step fills Implementation Intelligence.
7. **Validate** — schema + provenance + sanity rules.
8. **Publish** — `POST /api/evidence/ingest` inserts **new** records only when
   they pass duplicate detection and are *expected to improve* recommendation
   quality (gold/silver tier, required fields present).
9. **Benchmark** — re-run the category benchmark; record the delta.
10. **Learn** — update campaign status + costs; close out completed campaigns.

## Discovery principles

- **Target-first.** A campaign is created from a gap, then sources are sought for
  it — never the reverse.
- **Source types map to gaps.** Missing rollout strategy → engineering blogs /
  vendor case studies; missing validation gates / causal outcomes → government
  audits / SEC filings / peer-reviewed; missing breadth → search + curated seeds.
- **Reuse, don't re-crawl.** Discovery calls the engine's existing
  `SearchQueryGenerator`, `WebSearchScraper` (DuckDuckGo, no API key), and
  `evidence_seeds.yaml`. Fetch/parse uses the engine's crawl + docling/bs4 path
  behind a small pluggable adapter (dry-run fetcher for tests/CI).
- **Budget-capped.** Discovery/fetch is cheap; every LLM extraction call is
  budget-gated and counted. Campaign cost = sum of extraction + collection costs.

## Publish gate

A discovered record is **accepted** only if:
- no near-duplicate already exists (content hash or normalized org+title match);
- schema + provenance validation passes;
- it is *expected to improve* the category benchmark: it carries a meaningful
  evidence tier (gold/silver preferred) and/or fills a field the category
  benchmark flagged as missing.

Otherwise it is **rejected** (and the rejection is counted in campaign metrics).

## Campaign metrics

- sources discovered / accepted / rejected
- implementation-rich records created
- benchmark improvement (before → after, per category)
- cost per useful record
- cost per improved Decision Brief (category benchmark delta / campaign cost)

## Non-goals

- Not an autonomous web crawler. No indiscriminate crawling.
- No new second crawler implementation — reuse the engine framework.
- No publish-without-quality-gate. Provenance and validation always enforced.
