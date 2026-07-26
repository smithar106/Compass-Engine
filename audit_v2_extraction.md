# V2 Extraction Audit

## Current State

| Metric | Count |
|---|---|
| Total documents processed (v2) | 3,857 |
| Tier 1 (Gold) | 25 (0.6%) |
| Tier 2 (Silver) | 15 (0.4%) |
| Tier 3 (Bronze) | 649 (16.8%) |
| Rejected | 3,161 (82.0%) |
| No extraction (insufficient text) | 7 |
| V1 intervention docs upgraded to tier1 | 14 |
| New tier1 docs (not in V1) | 11 |
| V1 intervention docs **downgraded** | 246 |

---

## 1. Root Cause: Only 25 Tier 1

The bottleneck is **not the prompt** — it is the **document corpus**. Three problems:

### 1a. 42% of the corpus is Reddit noise (1,625 documents)
The crawl ingested Reddit authentication/redirect pages, not actual content. These are correctly rejected by the LLM but represent wasted throughput.

### 1b. 18% are academic papers (758 documents)
arXiv (662) + publisher sites (96). The LLM correctly classifies these as tier3 (academic papers proposing novel methods). A small fraction describe real implementations, but they are published as academic research, not business case studies.

### 1c. The remaining ~1,100 documents are mostly noise
Blog posts (dev.to: 227), tech news (TechCrunch, The Verge, Ars: 60), Twitter (59), vendor sites (54), personal projects (205), tutorials (46), unreadable PDFs (24). Genuine business implementation case studies with before/after metrics are **extremely rare** in this corpus.

**The corpus lacks curated business implementation sources** — vendor case study libraries (AWS, Salesforce, UiPath, ServiceNow), analyst reports (Gartner, Forrester), implementation partner blogs, or customer success pages.

### 1d. The corpus nearly doubled between v1 and v2 (2,005 → 3,857) but quality did not improve

---

## 2. Are Genuine Implementations Being Misclassified?

**Conclusion: No.** After auditing all 246 v1-intervention documents that v2 downgraded, the v2 classification is correct in essentially every case. Here is the breakdown:

### 159 rejected downgrades — none are tier1-worthy

| Category | Count | Examples |
|---|---|---|
| News articles (no implementation data) | ~60 | CDC vaccine $44M, GCHQ webcam intercept, OpenAI chip announcement |
| Personal/hobby blog posts | ~50 | "I built a keyboard tester", "hosting a website on a vape" |
| Product announcements | ~25 | Stripe Tax, Cloudflare WARP, Meta Llama release |
| Technical tutorials | ~15 | "Step-by-step CMS migration", "Server-Driven UI in Next.js" |
| Unreadable PDFs | ~9 | Binary PDF dumps |

### 79 tier3 downgraded — correctly identified as academic

All are arXiv papers or academic journal articles proposing novel methods/algorithms. A few describe implementations at real orgs (UK police, Utrecht radiology dept), but the source is an academic paper, not a business case study. These do **not** meet the tier1 bar of "real org implementation with before/after business metrics."

### 5 tier2 downgraded — correctly identified as industry research

Systematic reviews, surveys, aggregate statistics. Correctly classified.

---

## 3. Top 50 Highest-Scoring Rejected / Tier2 Records

All top 50 scored 80/100 on the V1-based scoring rubric (had: named org + problem + intervention + outcomes). **Every single one** was rejected by v2 for the same reason: **no baseline/before metrics**. Examples:

| # | Org | Problem | V2 Reason | Why Not Tier 1 |
|---|---|---|---|---|
| 1 | Exequtech | Shipping code with quality | Blog post, no before/after metrics | No baseline, not a case study |
| 2 | Panelbear | One-person SaaS infra | Technical architecture post | No organizational context |
| 3 | OpenAI | ARC-AGI benchmark | News about benchmark score | Not an operational business problem |
| 4 | comma.ai | Cloud cost avoidance | Engineering blog post | No measured outcomes |
| 5 | Shopify | React Native adoption | No quantitative baseline | Subjective claim only |
| 6 | TinyPilot | Website redesign | Blog post without metrics | Anecdotal only |
| 7 | American Airlines | Yield management | Historical review (tier2) | Industry research, not implementation |
| 8 | InvGate | CDN migration | No quantitative baseline | Missing metrics |
| 9 | Google DeepMind | AlphaGo | AI research, not business ops | Not a business problem |
| 10 | Starsky Robotics | Autonomous trucking | Company shutdown narrative | No outcomes measured |

Full list of 50 is in the analysis output above. The pattern is uniform: V1 was too permissive (extracted anything with an org name), V2 correctly requires baseline metrics + operational business context.

---

## 4. Recommendations

### 4a. Curate the document corpus (highest impact)

| Action | Expected Gain |
|---|---|
| Add vendor case study libraries (aws.amazon.com/solutions/case-studies, salesforce.com/case-studies, uiPath.com/resources/case-studies, servicenow.com/case-studies) | +200-400 high-quality case studies |
| Add analyst implementation reports (Gartner case studies, Forrester) | +50-100 |
| Add engineering blogs with post-mortem metrics (Stripe, Shopify, Slack, Netflix, Uber engineering) | +100-200 |
| Remove Reddit from crawl targets entirely | Reduces noise by 42% |
| Filter arXiv/academic sources to only include papers with real org deployment | Reduces academic noise by 80% |

**Without corpus improvement, no prompt change will meaningfully increase tier1 count.**

### 4b. Prompt changes (moderate impact)

| Change | Rationale |
|---|---|
| **Do NOT lump tier3 with rejected.** The prompt says "If rejected/**tier3**: ONLY output minimal." This treats academic papers the same as noise. Separate them — tier3 should output full extraction if the paper describes a real org deployment. | Could reclaim 5-10 tier1 records from academic case studies |
| **Add a tier3a subcategory**: "Academic paper WITH real org implementation and measured outcomes" should be eligible for tier1 treatment. | Prevents genuine academic case studies from being discarded |
| **Relax baseline metrics requirement** to "baseline description OR baseline metrics" rather than requiring both. Many genuine case studies describe the before state qualitatively. | Could reclaim 5-15 records that have org + problem + outcomes but missing structured baseline numbers |
| **Fix the prompt list field** — line 16 says `"evidence_tier": "tier1/2/3/rejected"` in the minimal output format for rejected/tier3. This is confusing — should be just the specific tier assigned. | Improves classification clarity |
| **Add response_format** — DeepSeek doesn't support `json_object` enforcement, which would reduce JSON parse errors. | Minor reliability improvement |

### 4c. Pipeline changes (low impact)

| Change | Rationale |
|---|---|
| **Store tier2 and tier3 records in the DB** alongside tier1. Currently `11_map_v2_to_db.py` only stores tier1 (line 72: `if extraction.get("evidence_tier") != "tier1": continue`). Tier2 industry benchmarks are valuable for the recommendation engine. | Adds 15 tier2 + 649 tier3 records to the evidence base |
| **Add a confidence score** per extraction (how certain is the LLM about the classification). Records with high confidence but borderline content could be flagged for review. | Enables human-in-the-loop curation |
| **Seed the DB with known high-quality case studies** as a bootstrap set before the next extraction run. | Guarantees minimum evidence quality |

### 4d. Recommendation engine changes (medium impact)

Currently the API uses DB records to compute evidence tiers (gold/silver/bronze). With only 25 records, the evidence base is thin. Options:

| Change | Rationale |
|---|---|
| **Keep v1 baseline in the DB** alongside v2 tier1 records. V1 had 268 records (even if noisy, it provides more signal). | Doubles usable records from 25 to ~280 |
| **Merge v1 + v2 data**: use V2 extraction quality but fall back to V1 data when V2 doesn't have a record. | Best of both worlds |

---

## Summary

**The v2 tier1 count of 25 is correct given the corpus.** The pipeline is not misclassifying genuine business implementations — those don't exist in the corpus. The solution is to **curate better source documents**, not loosen the tier1 criteria. Laxing the prompt would let in the same noise V1 suffered from (268 records that looked like interventions but lacked baseline metrics).
