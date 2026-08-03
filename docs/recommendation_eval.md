# Recommendation Evaluation System

The evaluation system measures whether the ten-factor retrieval and the
recommendation engine actually do what we think, and captures customer outcomes
as the internal evidence moat. It does **not** add a more sophisticated model —
it instruments the current one.

## 1. Retrieval evaluation set

`compass_agent/eval_set.py` defines representative Compass requests; each has a
profile and relevance labels as deterministic predicates (workflow + canonical
industry + evidence tier + result status), so the eval runs against any record
pool and is reproducible. Labels are seed/provisional and should be refined by a
human reviewer.

`compass_agent/retrieval_eval.py` measures, per request and aggregated:

- **relevant-record recall @ 10 / 25 / 50**
- **irrelevant-record rate in the top K**
- **intervention-family ranking accuracy** (top-10 families vs expected)
- **field sensitivity** (rank displacement + top-1 flip rate when one profile
  field is perturbed)
- **weight sensitivity** (rank displacement per ±0.05 weight perturbation)

CLI: `python -m compass_agent eval retrieval` and `eval sensitivity`.

### Baseline (first run, 1,306-record backfilled DB)

- recall@10 **0.42**, recall@25 **0.52**
- irrelevant@10 **0.64** (too high)
- Per-request: onboarding / lead qualification / contract review / supply chain
  reach recall 1.0; invoice processing / ticketing / manufacturing / customer
  health / financial close reach 0.0
- Field & weight sensitivity ≈ **0** — the ranking barely changes under
  perturbation.

**What the baseline reveals:** retrieval is effectively **workflow-dominated**.
The workflow factor (now with keyword containment for query slugs vs free-text
record workflows) carries the signal; problem-token, industry, size, and
geography contribute ~0 for most records on this data (sparse fields, short
query problem text, mismatched workflow vocabularies). The system is therefore
*stable under weight changes* — but partly because it is not using most of the
factor space. That is the actionable finding: raise the other factors' signal
(coverage + matching), then re-measure.

## 2. Weight sensitivity testing

`eval sensitivity` perturbs each `CONTEXT_FACTOR_WEIGHTS` weight ±0.05
(renormalized) and reports the top-25 rank displacement. The ideal system is
stable under small changes but responsive to genuinely important profile
changes. Current result: near-zero sensitivity because one factor dominates.

## 3. Recommendation traceability

Every recommendation now carries an internal `trace`:

```
primary_reasons:  [{"factor": "workflow", "raw": 0.92}, {"factor": "problem", "raw": 0.7}, ...]
evidence:         {"gold": 3, "silver": 4, "mixed": 2, "total": 9}
primary_uncertainty: "Few comparable organizations at the customer's employee scale"
```

Retained for debugging and defensibility; not necessarily shown in the UI.

## 4. Counterevidence

Each recommendation surfaces `counterevidence` — comparables that argue
*against* the top pick (failed/abandoned implementations, negative outcome
directions), e.g.:

> "Acme attempted AP automation but the implementation was abandoned — process
> standardization was incomplete."

This differentiates Compass from software that merely rationalizes its top
result.

## 5. Outcome feedback (the internal evidence moat)

`POST /api/outcomes` records what happened after a customer acts: accepted?
implemented? blueprint followed? realized cost, implementation duration,
measured result, unexpected constraints, and whether Compass would recommend the
same intervention retrospectively. `GET /api/outcomes` lists them.

The agent grows the **external** record pool (Source Libraries); customer
outcomes build the **internal** evidence moat — the most valuable proprietary
dataset, because it ties recommendations to realized business results.

## Run it

```bash
python -m compass_agent eval retrieval
python -m compass_agent eval sensitivity
```
