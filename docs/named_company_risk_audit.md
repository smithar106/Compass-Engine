# Named-Company Risk Audit

**Date:** 2026-08-24
**Scope:** Public Compass prototype (`compass-solutions.up.railway.app/prototype`) and the engine risk/counterevidence generation that feeds it.
**Trigger:** A live risk statement named real companies (Finastra, Tetra Pak) and asserted they "showed weaker results or encountered challenges."

---

## Root cause

`compass_collector/api/service.py`, `_build_risks()` (lines ~1302–1318):

```python
failed_orgs = set()
for c in comparables:
    if c.evidence_tier in ("supporting", "bronze") and c.organization:
        failed_orgs.add(c.organization)

if failed_orgs:
    org_names = ", ".join(list(failed_orgs)[:2])
    risks.append({
        "title": "Mixed outcomes in comparable implementations",
        "explanation": f"Some comparable implementations ({org_names}) showed weaker "
                       f"results or encountered challenges. ...",
    })
```

This conflates an **evidence-documentation tier** with a **results claim**.

Per `compass_collector/api/evidence_tier.py`, the tiers mean:

- `gold` — fully quantified, known deployment, executive-ready
- `decision_grade` — strong implementation with a quantified outcome
- `supporting` — **adds context; not enough for a primary recommendation alone**
- `bronze` — legacy alias for `supporting`

`supporting`/`bronze` describe **how completely the record is documented**, not
whether the company's project succeeded. The code therefore names real
companies and asserts they "showed weaker results" **based on documentation
quality alone, with no outcome evidence and no source.**

A second path, `_build_counterevidence()` (lines ~1251–1278), names
organizations with `implementation_status in ("failed","abandoned")` or a
negative metric direction. It did not fire for the 10 prototype problems, but
it is the same class of risk and must meet the same source bar.

## What is live on the public prototype today

The named-company risk statement is currently generated for 6 of the 10
prototype problems:

| Company named | Shown claim | Linked source? | Source supports the claim? | Risk |
|---|---|---|---|---|
| Finastra | "showed weaker results or encountered challenges" | **NO** (0/3 records have a source document) | **NO** | **HIGH** |
| Tetra Pak | same | Yes (UiPath case study) | **NO — source contradicts it** (case study reports success: days→hours, 99% accuracy) | **HIGH** |
| Razer | same | Partial (2/3) | **NO** documented negative outcome | **HIGH** |
| Coterie Baby | same | **NO** (0/1) | **NO** | **HIGH** |
| Nissin Foods | same | **NO** (0/1) | **NO** | **HIGH** |
| NatWest | same | **NO** (0/9) | **NO** | **HIGH** |
| Salesforce | same | Partial (13/24) | **NO** documented negative outcome | **HIGH** |

**All 7 named companies are HIGH RISK.** None has a source that explicitly and
specifically supports the negative characterization. Tetra Pak is the most
damaging: its linked source is a UiPath case study titled "Tetra Pak Cuts
Process Time with Agentic AI" reporting a successful outcome — the prototype
claim is the opposite of what the cited source says.

## Why this is a distinct class of exposure

- An aggregate claim ("10,000+ records") is not checkable by a third party.
- A statement that a **named, identifiable company** "showed weaker results or
  encountered challenges" is a discrete factual assertion about a specific
  third party. It is checkable, and here it is **unsupported and, for Tetra
  Pak, false relative to the cited source.**
- This is precisely the failure mode Compass markets itself as fixing
  (unsourced AI assertions presented as fact). Shipping it is both a
  reputational and a potential legal exposure.

## Immediate action (applied)

1. `_build_risks`: the named-company negative claim is **removed**. Replaced
   with a generic, honest statement that names no organization.
2. `_build_counterevidence`: now requires a **linked source document** before a
   company may be named, and never names a company on a tier/status alone.
3. Redeploy the engine so the public prototype no longer shows named negative
   claims.

## Standing rule (recommended)

No named real company may appear in a negative, comparative, or critical
context in any Compass surface unless **all** of the following hold:

- (a) a direct link to a primary source document is attached and visible,
- (b) the source **explicitly** documents the specific negative outcome as
  characterized (not inferred from tier, status, or a metric sign), and
- (c) a human reviewer (ideally counsel) has approved the characterization.

Until then, negative/cautionary statements must be **generic** (no company
names) or omitted.
