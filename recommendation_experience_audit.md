# Recommendation Experience Audit

## 1. Assessment Inputs Currently Collected

| Input | Frontend Question | API Field | Type | Collected |
|---|---|---|---|---|
| Problem statement | "Which statement best describes your situation?" | `problem_statement` | String (multi-choice) | Yes |
| Department | "Which department owns this workflow?" | `business_function` | String (multi-choice) | Yes |
| Workflow maturity | "How would you describe the current workflow?" | `workflow` (mapped) | String (multi-choice) | Yes |
| Workflow frequency | "How often does this workflow run?" | `workflow_frequency` | String (multi-choice) | Yes |
| People involved | "How many people are involved?" | `people_involved` | String (range) | Yes |
| Handoffs | "How many handoffs occur in this process?" | `handoffs` | String (range) | Yes |
| Current tools | "What tools or software do you currently use here?" | `current_tools` | String[] | Yes |
| Exception rate | "How many exceptions or edge cases arise?" | `exception_rate` | String (range) | Yes |
| Budget range | "Do you have a budget for addressing this?" | `budget_range` | String (range) | Yes |
| Implementation timeline | "What is your expected timeline for improvement?" | `implementation_timeline` | String (choice) | Yes |
| Risk tolerance | "What is the risk of getting this wrong?" | `business_risk` | String (choice) | Yes |
| Process stability | "How stable is this process?" | `process_stability` | String (choice) | Yes |
| Prior attempts | "Have you tried to improve this before?" | `previous_attempts` | String (choice) | Yes |
| Desired outcome | "What outcome matters most to you?" | `desired_outcome` | String (choice) | Yes |

## 2. Inputs Required for Financial Estimates

| Required Input | Collected? | Notes |
|---|---|---|
| Annual workflow volume | **No** | Not collected by assessment |
| Current handling time per item | **No** | Not collected |
| Loaded labor cost per hour | **No** | Not collected |
| Number of people involved | Partially | Collected as range (e.g., "4–10"), not as integer |
| Workflow frequency | Partially | Collected as qualitative (e.g., "Daily"), not as transactions/time unit |

**Verdict:** Organization-specific financial estimates cannot be calculated defensibly with the current assessment.

## 3. Financial-Estimate Eligibility Policy

Compass now follows a strict policy:

- **Hours returned:** Requires annual workflow volume + current handling time + evidence-supported improvement range. Always returns `insufficient_input` with current assessment.
- **Annual labor savings:** Requires annual workflow volume + current handling time + loaded labor cost + evidence-supported improvement range. Always returns `insufficient_input` with current assessment.
- **Software-cost savings:** Requires current software cost + applicable evidence + intervention-specific cost basis. Not implemented in current assessment.

When inputs are insufficient, `ImpactEstimate` returns:
- `status: "insufficient_input"`
- `missing_inputs: [...]` — listing exactly what's needed
- `what_can_be_reported: "Evidence-derived outcome ranges..."` — guiding user to available data
- `prompt_for_user: "Provide annual workflow volume..."` — concrete request

No phantom defaults are used. No arbitrary headcount (was 50), labor rate (was $50/hr), or annual hours (was 2000) assumptions remain.

## 4. Outcome-Range Aggregation Method

Outcome ranges are calculated from `normalized_metrics` across comparable implementations:

1. Metrics are grouped by normalized key (e.g., `cycle_time`, `error_rate`)
2. Within each group, compatibility is checked: same unit, same direction
3. Values are collected and sorted
4. Aggregation depends on sample size:
   - **n >= 6:** IQR-based outlier filtering (Q1 - 1.5\*IQR to Q3 + 1.5\*IQR); `calculation_method = "median_iqr"`
   - **n >= 3:** Min/max range; `calculation_method = "median_minmax"`
   - **n = 1:** Single value; `calculation_method = "single_value"`
5. Median is the central value
6. Company-wide metrics are excluded early

## 5. Metric Compatibility Rules

Metrics are considered compatible when ALL of the following are true:

- Same normalized metric key (e.g., both are `cycle_time`)
- Same unit type (`%` with `%`, `currency` with `currency`, `number` with `number`)
- Neither is company-wide (checked by `_is_company_wide_metric`)
- Both have parsable numeric values

Incompatible metrics produce an `OutcomeRange` with `directly_comparable = False` and a `compatibility_notes` explanation.

## 6. Ranking Dimensions and Weights

The ranking engine (`recommendation.py`) produces confidence scores (0–100) across these dimensions:

| Dimension | Weight | Source |
|---|---|---|
| Comparable volume | ~20% | Count of total comparable implementations |
| Family-specific count | ~10% | Count per intervention family |
| Outcome measurement | ~25% | Whether implementations documented quantified business outcomes |
| Outcome consistency | ~10% | Ratio of successful to total implementations |
| Evidence quality | ~10% | Average evidence score across comparables |
| Org diversity | ~5% | Number of unique organizations |
| Negative evidence penalty | ~20% (max) | Ratio of failed/abandoned implementations |
| Source reliability | ~8% | Non-vendor-reported sources |
| Baseline/documentation | ~5% | Presence of cost/savings/implementation data |

These scores are surfaced in the response as `why_ranked_first` (executive summary) and in the frontend.

## 7. Why the Test Recommendation Ranked First

For a test input (`operations`, `process_automation`, `professional_services`):

The top recommendation (Workflow Automation) ranked first because:
- Highest number of comparable implementations specific to the workflow
- Strongest outcome documentation (gold/silver source count)
- Most consistent results across comparable implementations
- Best workflow fit score based on similarity matching

The `why_ranked_first` field provides the executive summary with supporting reasons, tradeoffs, and alternative differences.

## 8. Why Alternatives Ranked Lower

Alternatives (Software, AI, Process Redesign) ranked lower for:
- Fewer comparable implementations matching the workflow
- Lower evidence tier (fewer gold/silver sources)
- Lower outcome consistency scores
- Higher evidence requirements (e.g., AI requires training data availability)
- Longer time-to-value estimates

## 9. Comparable Selection Rules

Comparable implementations are selected by `retrieval.py` using:

1. **Similarity scoring** across: workflow (40%), company size (20%), industry (15%), intervention type (15%), outcome (10%)
2. **Deduplication** by organization (prevent multiple records from same org)
3. **Evidence tier filtering** (`classify_tier_for_comparable` rejects poor quality)
4. **Minimum similarity threshold** (score > 0 to be included)
5. **Penalty** for company-wide metrics, vendor-reported outcomes, failed/abandoned status

Top displayed evidence prioritizes: workflow similarity → evidence tier → metric completeness → organizational similarity

## 10. Example Comparable Relevance Explanation

> "Adobe applied rule-based routing and workflow automation — High similarity to the assessed workflow"

Each `ComparableEvidence` includes: workflow context, intervention, outcome summary, relevance explanation, limitations, evidence tier, and evidence score.

## 11. Assumptions and Information Gaps

Each recommendation includes `assumptions_detail` and `information_gaps`:

**Assumptions** (examples):
- Limited comparable evidence (X implementations)
- Workforce size and involvement not provided
- Workflow volume not provided
- Exception rate not considered in estimates

Each includes: title, explanation, effect_on_recommendation, effect_on_confidence, resolution_action.

**Information gaps** (examples):
- Annual workflow volume and handling time
- Loaded labor cost
- More comparable implementations in your industry
- Preferred implementation timeline

Each includes: title, explanation, effect_on_recommendation, effect_on_confidence, resolution_action.

## 12. Next Validation-Step Logic

Each recommendation includes `next_validation_step` generated based on:

- **Rank** (primary vs alternative)
- **Evidence quantity** (fewer than 5 comparables → baseline measurement)
- **Category** (intervention-specific considerations)

Fields: action, purpose, owner, duration, required_inputs, success_criteria, decision_enabled.

If fewer than 5 comparables: "Measure a 4-week baseline for the current workflow"
If 5+ comparables: "Run a bounded pilot of the recommended approach"

## 13. Server-Side PDF Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│  POST /api/  │────>│  run_recommen-   │────>│  storage.py    │
│ recommenda-  │     │  dation()        │     │  (JSON file)   │
│ tions        │     │                  │     │                │
└──────────────┘     └──────────────────┘     └───────┬────────┘
                                                       │
                                                       ▼
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│  GET /api/   │────>│  load_recommen-  │────>│  report.py     │
│ recommenda-  │     │  dation()        │     │  (HTML → PDF)  │
│ tions/{id}/  │     │                  │     │  weasyprint    │
│ report.pdf   │     └──────────────────┘     └────────────────┘
└──────────────┘
```

- HTML template is render-only (no nav, buttons, accordions)
- PDF generated server-side via weasyprint
- Fallback to HTML if weasyprint unavailable

## 14. Persistence Design

Recommendation results are persisted as JSON files in `data/recommendations/{recommendation_id}.json`:

```
{
  "recommendation_id": "...",
  "_schema_version": "3.0.0",
  "_stored_at": "2026-07-26T...",
  "engine_version": "3.0.0",
  "dataset_version": "v3",
  "generated_at": "...",
  "assessment_summary": {...},
  "recommendations": [...],
  "methodology": {...}
}
```

## 15. Files Changed

### Engine (`compass-collector`)

| File | Change |
|---|---|
| `compass_collector/api/schemas.py` | Added OutcomeRange, WhyRankedFirst, AlternativeComparison, SpecificIntervention, updated Assumption/InformationGap/NextValidationStep, updated ComparableEvidence |
| `compass_collector/api/service.py` | Rewrote _estimate_impact (strict policy), _calculate_outcome_ranges (compatibility rules), added _generate_specific_intervention, _build_ranking_explanation, _build_alternative_comparison, updated _classify_comparables, added persistence call |
| `compass_collector/api/app.py` | Added GET /api/recommendations/{id}/report and /report.pdf endpoints |
| `compass_collector/api/storage.py` | NEW: File-based persistence for recommendation results |
| `compass_collector/api/report.py` | NEW: HTML report template + weasyprint PDF generation |
| `requirements.txt` | Added weasyprint |
| `data/audits/assessment_input_inventory.json` | NEW: Complete input audit |
| `tests/test_recommendation.py` | NEW: 23 unit tests for recommendation service |

### Frontend (`Compass-AI-Website`)

| File | Change |
|---|---|
| `src/app/assessment/results/page.tsx` | Rebuilt page with decision-brief hierarchy; investigation summary, outcome ranges primary, why-ranked-first, alternative comparison, assumptions/gaps, next-step detail; updated PDF to use server endpoint |
| `src/app/api/recommendations/pdf/route.ts` | NEW: Server-side PDF proxy route to engine |

## 16. API Response Before and After

### Before (old schema)

```
POST /api/recommendations
{
  "recommendations": [{
    "rank": 1,
    "title": "Workflow Automation",
    "impact": {
      "annual_savings": {"status": "calculated", "expected": 500000, ...},
      "annual_hours_returned": {"status": "calculated", "expected": 5000, ...}
    },
    "comparable_implementations": [{
      "organization": "Company A",
      "outcome_summary": "Cost: 30%",
      "evidence_tier": "silver"
    }]
  }]
}
```

### After (new schema)

```
POST /api/recommendations
{
  "recommendations": [{
    "rank": 1,
    "title": "Workflow Automation",
    "specific_action": "Standardize intake and automate approval routing...",
    "specific_intervention": {
      "title": "...",
      "required_changes": [...],
      "scope_boundaries": [...]
    },
    "impact": {
      "annual_savings": {
        "status": "insufficient_input",
        "missing_inputs": ["people_involved", "workflow_frequency", ...],
        "what_can_be_reported": "Evidence-derived outcome ranges..."
      }
    },
    "outcome_ranges": [{
      "metric_key": "cycle_time",
      "metric_label": "Cycle time",
      "unit": "%",
      "direction": "reduction",
      "low": 22.0, "median": 33.0, "high": 41.0,
      "sample_size": 5, "gold_count": 2,
      "directly_comparable": true,
      "calculation_method": "median_iqr"
    }],
    "why_ranked_first": {
      "summary": "Workflow automation ranked first because...",
      "supporting_reasons": [...],
      "tradeoffs": [...],
      "alternative_differences": [...]
    },
    "alternative_comparison": {
      "evidence_strength": "Strong",
      "implementation_complexity": "Low to Medium",
      ...
    },
    "comparable_implementations": [{
      "organization": "Company A",
      "workflow_context": "Support ticket intake...",
      "intervention": "Custom intake automation",
      "outcome_summary": "Cycle time: 30%",
      "relevance_explanation": "High similarity to assessed workflow",
      "limitations": "Did not publish implementation cost",
      "evidence_tier": "silver",
      "evidence_score": 75
    }],
    "assumptions_detail": [{"title": "...", "explanation": "...", ...}],
    "information_gaps": [{"title": "...", "explanation": "...", ...}],
    "next_validation_step": {
      "action": "Run a bounded pilot...",
      "purpose": "...",
      "owner": "...",
      "duration": "...",
      "required_inputs": [...],
      "success_criteria": "...",
      "decision_enabled": "..."
    }
  }]
}
```

## 17. Revised Frontend Sections

The frontend page is structured as an executive decision brief:

1. **Header** — Title, status badge, metadata, PDF download
2. **Investigation summary** — Problem, workflow, evidence, confidence
3. **Recommended path** — Specific action, outcome ranges (primary), why-ranked-first with tradeoffs, comparable implementations (full context), confidence
4. **Alternative approaches** — Comparison matrix per alternative
5. **Risks and mitigations** — Category, explanation, mitigation
6. **Assumptions and information gaps** — Title, explanation, effect, resolution
7. **Next validation step** — Action, purpose, owner, duration, inputs, criteria
8. **Methodology** — About this analysis

## 18. Sample Generated PDF

The PDF report includes:

- Page 1: Executive decision (recommendation, summary, why ranked first, potential impact)
- Page 2: Alternatives evaluated (comparison matrix)
- Page 3: Comparable implementations (full context cards)
- Page 4: Risks and mitigations
- Page 5: Assumptions, gaps, next step, methodology

Generated via: `GET /api/recommendations/{rec_id}/report.pdf` (weasyprint)

## 19. Test Results

All 23 tests pass:

```
test_assumptions_created_when_few_comparables ... ok
test_information_gaps_created ... ok
test_next_step_created ... ok
test_insufficient_input_when_missing_volume ... ok
test_missing_inputs_listed ... ok
test_what_can_be_reported_when_comparables_exist ... ok
test_large_currency_flagged ... ok
test_small_currency_not_flagged ... ok
test_company_wide_detection ... ok
test_normalize_name ... ok
test_normalize_value ... ok
test_company_wide_metrics_excluded ... ok
test_incompatible_units_excluded ... ok
test_multiple_comparable_metrics ... ok
test_single_metric ... ok
test_source_record_ids ... ok
test_has_summary_and_reasons ... ok
test_returns_none_without_recs ... ok
test_report_html_generates ... ok
test_category_based_generation ... ok
test_falls_back_to_top_example ... ok
test_software_intervention ... ok
test_specific_intervention_object ... ok

Ran 23 tests in 0.001s
OK
```

## 20. Known Limitations

1. **weasyprint system dependencies**: The PDF library (weasyprint) requires system packages (cairo, pango, gdk-pixbuf). If these aren't available on Railway, the PDF endpoint falls back to returning HTML for browser print-to-PDF.

2. **Assessment input gap**: Four critical inputs for financial estimates are not collected (annual volume, handling time, labor cost, tool-specific costs). Adding these requires frontend changes.

3. **Ranking trace**: A formal `data/audits/latest_ranking_trace.json` with per-candidate dimension-by-dimension breakdown is not yet produced. The confidence scores exist in the engine but are not exposed as separate trace output.

4. **No frontend tests**: The frontend page.tsx changes (Phase 14-15) do not have automated tests. Manual verification is needed.

5. **No Supabase persistence**: Recommendation results are stored as engine filesystem JSON, not in Supabase. Sufficient for single-instance, but not horizontally scalable.

6. **Comparable selection thresholds**: The minimum display threshold for comparable implementations is not formally defined. Some low-relevance records may still appear if total comparables are few.

7. **Large outcome context**: While `_add_large_outcome_context` exists, it is not yet called in `_classify_comparables` flow. Large monetary values in outcome ranges may still display without attribution context.

8. **PDF report not cached**: Generated PDFs are not cached or persisted. Each request regenerates the PDF from the stored JSON payload.
