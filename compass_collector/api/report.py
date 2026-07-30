"""Report HTML template and PDF generation.

Generates a clean, print-optimized structured report from a completed
recommendation payload. Uses weasyprint for PDF conversion.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("compass-engine.report")


def _v(val) -> str:
    if val is None:
        return ""
    return str(val)


def _pct(val) -> str:
    if val is None:
        return ""
    return f"{val:.0f}%"


def _currency(val) -> str:
    if val is None:
        return ""
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


def _direction_emoji(d: str) -> str:
    if d == "reduction":
        return "\u2193"
    if d == "improvement":
        return "\u2191"
    return "\u2192"


_STYLES = """
<style>
  @page {
    size: letter;
    margin: 0.9in 0.85in 1in 0.85in;
    @bottom-center { content: counter(page); font-size: 8pt; color: #999; font-family: Georgia, "Times New Roman", serif; }
  }
  * { box-sizing: border-box; }
  body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 9.5pt; line-height: 1.6; color: #1a1f2b; margin: 0; padding: 0; }
  h1 { font-family: Georgia, "Times New Roman", serif; font-size: 20pt; font-weight: 700; margin: 0 0 6pt 0; color: #0f172a; }
  h2 { font-family: Georgia, "Times New Roman", serif; font-size: 14pt; font-weight: 700; margin: 28pt 0 10pt 0; color: #0f172a; border-bottom: 1.5pt solid #d0d5dd; padding-bottom: 6pt; }
  h3 { font-family: Georgia, "Times New Roman", serif; font-size: 11pt; font-weight: 700; margin: 18pt 0 8pt 0; color: #344054; }
  p { margin: 0 0 8pt 0; color: #475467; line-height: 1.6; }
  .logo { font-family: Georgia, "Times New Roman", serif; font-size: 16pt; font-weight: 700; color: #2D6A4F; margin-bottom: 4pt; }
  .meta { font-size: 8pt; color: #98a2b3; margin-bottom: 20pt; border-bottom: 1pt solid #eaecf0; padding-bottom: 12pt; }
  .meta span { display: inline-block; margin-right: 20pt; }
  .summary-box { background: #f9fafb; border: 1pt solid #eaecf0; padding: 14pt 16pt; margin-bottom: 16pt; }
  .summary-box p { font-size: 9.5pt; margin: 3pt 0; }
  .summary-box strong { color: #1d2939; }
  .score-badge { display: inline-block; background: #2D6A4F; color: #fff; font-size: 18pt; font-weight: 700; padding: 4pt 12pt; border-radius: 4pt; font-family: Georgia, serif; }
  .score-badge-alt { display: inline-block; background: #344054; color: #fff; font-size: 14pt; font-weight: 700; padding: 3pt 10pt; border-radius: 4pt; font-family: Georgia, serif; }
  .recommended-tag { display: inline-block; background: #2D6A4F; color: #fff; font-size: 7pt; font-weight: 700; padding: 2pt 8pt; border-radius: 3pt; text-transform: uppercase; letter-spacing: 0.08em; }
  .alternative-tag { display: inline-block; background: #475467; color: #fff; font-size: 7pt; font-weight: 700; padding: 2pt 8pt; border-radius: 3pt; text-transform: uppercase; letter-spacing: 0.08em; }
  .outcome-grid { display: flex; flex-wrap: wrap; gap: 10pt; margin-bottom: 16pt; }
  .outcome-card { background: #f9fafb; border: 1pt solid #eaecf0; padding: 10pt 14pt; flex: 1 0 170pt; }
  .outcome-card .value { font-family: Georgia, "Times New Roman", serif; font-size: 15pt; font-weight: 700; color: #1d2939; }
  .outcome-card .label { font-size: 7pt; font-weight: 700; color: #667085; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2pt; }
  .outcome-card .count { font-size: 7pt; color: #98a2b3; margin-top: 1pt; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16pt; font-size: 8.5pt; }
  th { background: #f9fafb; text-align: left; padding: 7pt 9pt; font-weight: 700; color: #344054; border-bottom: 1.5pt solid #d0d5dd; font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.05em; }
  td { padding: 6pt 9pt; border-bottom: 1pt solid #eaecf0; color: #475467; }
  .intervention-card { border: 1.5pt solid #d0d5dd; padding: 14pt 16pt; margin-bottom: 14pt; }
  .intervention-card.recommended { border-color: #2D6A4F; background: #f6fef9; }
  .intervention-card h3 { margin: 0 0 6pt 0; }
  .score-row { display: flex; gap: 6pt; flex-wrap: wrap; margin: 8pt 0; }
  .score-dim { background: #f9fafb; border: 1pt solid #eaecf0; padding: 6pt 10pt; flex: 1 0 140pt; font-size: 8pt; }
  .score-dim .dim-label { font-weight: 700; color: #344054; font-size: 7pt; text-transform: uppercase; letter-spacing: 0.05em; }
  .score-dim .dim-score { font-family: Georgia, serif; font-size: 12pt; font-weight: 700; color: #1d2939; }
  .score-dim .dim-reason { font-size: 7.5pt; color: #667085; }
  .comparison-grid { display: flex; gap: 8pt; margin-bottom: 14pt; }
  .comparison-col { flex: 1; border: 1pt solid #eaecf0; padding: 10pt; font-size: 8pt; }
  .comparison-col h4 { font-size: 9pt; margin: 0 0 6pt 0; }
  .comparison-col .stat { margin: 3pt 0; }
  .comparison-col .stat-label { color: #667085; font-size: 6.5pt; text-transform: uppercase; letter-spacing: 0.05em; }
  .comparison-col .stat-value { font-weight: 600; color: #1d2939; }
  .tier-gold { background: #fffaeb; color: #b54708; font-size: 6.5pt; font-weight: 700; padding: 2pt 6pt; border: 1pt solid #fedf89; }
  .tier-silver { background: #f2f4f7; color: #475467; font-size: 6.5pt; font-weight: 700; padding: 2pt 6pt; border: 1pt solid #d0d5dd; }
  .tier-bronze { background: #fff6ed; color: #c4320a; font-size: 6.5pt; font-weight: 700; padding: 2pt 6pt; border: 1pt solid #fed7aa; }
  .risk-box { background: #fef3f2; border: 1pt solid #fecdca; padding: 10pt 14pt; margin-bottom: 10pt; }
  .risk-box h4 { font-family: Georgia, "Times New Roman", serif; font-size: 10pt; font-weight: 700; color: #912018; margin: 0 0 4pt 0; }
  .risk-box p { font-size: 8.5pt; color: #912018; margin: 0 0 3pt 0; }
  .risk-box .mitigation { font-size: 8pt; color: #2D6A4F; font-weight: 600; }
  .gap-box { background: #f9fafb; border: 1pt solid #eaecf0; padding: 10pt 14pt; margin-bottom: 8pt; }
  .gap-box h4 { font-size: 9pt; font-weight: 700; color: #1d2939; margin: 0 0 3pt 0; }
  .gap-box p { font-size: 8pt; color: #475467; margin: 0; }
  .next-box { background: #f0fdf4; border: 1.5pt solid #86efac; padding: 14pt 16pt; margin: 18pt 0; }
  .next-box h3 { font-family: Georgia, "Times New Roman", serif; font-size: 12pt; font-weight: 700; color: #166534; margin: 0 0 6pt 0; }
  .next-box p { font-size: 9pt; color: #166534; margin: 0 0 3pt 0; }
  .next-box .detail { font-size: 8pt; color: #15803d; }
  .page-break { page-break-before: always; }
  ul { margin: 4pt 0 10pt 0; padding-left: 18pt; }
  li { margin-bottom: 3pt; font-size: 9pt; color: #475467; }
  .comparables-grid { margin-bottom: 16pt; }
  .comparable-card { border: 1pt solid #eaecf0; padding: 10pt 14pt; margin-bottom: 8pt; }
  .comparable-card .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5pt; }
  .comparable-card .org { font-weight: 700; font-size: 9.5pt; color: #1d2939; }
  .comparable-card .detail { font-size: 8.5pt; color: #475467; margin: 1pt 0; }
  .comparable-card .limitation { font-size: 7.5pt; color: #98a2b3; font-style: italic; }
  .footer-note { border-top: 1pt solid #eaecf0; padding-top: 10pt; margin-top: 24pt; font-size: 7.5pt; color: #98a2b3; }
</style>
"""


def _score_component_rows(breakdown: dict) -> str:
    if not breakdown:
        return ""
    rows = []
    for key, label in [
        ("problem_alignment", "Problem Alignment"),
        ("organizational_similarity", "Org Similarity"),
        ("goal_alignment", "Goal Alignment"),
        ("evidence_strength", "Evidence Strength"),
        ("implementation_fit", "Implementation Fit"),
        ("outcome_consistency", "Outcome Consistency"),
    ]:
        comp = breakdown.get(key, {})
        if comp:
            score_val = comp.get("score", 0)
            if score_val is None:
                score_val = 0
            rows.append(f"""
            <div class="score-dim">
              <div class="dim-label">{label}</div>
              <div class="dim-score">{float(score_val):.0f}</div>
              <div class="dim-reason">{_v(comp.get('reason', ''))}</div>
            </div>
            """)
    return '<div class="score-row">' + "".join(rows) + "</div>"


def _intervention_card(si: dict, is_recommended: bool) -> str:
    rank = si.get("rank", 0)
    name = si.get("intervention_name", "")
    score = si.get("match_score", 0)
    label = si.get("label", "alternative")
    evidence = si.get("evidence_strength", "")
    difficulty = si.get("implementation_difficulty", "")
    timeframe = si.get("estimated_timeframe", "")
    rationale = si.get("rationale", "")
    risks = si.get("top_risks", [])
    advantages = si.get("key_advantages", [])
    tradeoffs = si.get("key_tradeoffs", [])
    breakdown = si.get("score_breakdown", {})
    comparisons = si.get("comparable_implementations", [])

    tag = '<span class="recommended-tag">Recommended</span>' if is_recommended else '<span class="alternative-tag">Alternative</span>'
    badge_class = "score-badge" if is_recommended else "score-badge-alt"

    comp_rows = ""
    for c in comparisons[:3]:
        comp_rows += f"""
        <div class="comparable-card">
          <div class="header"><span class="org">{_v(c.get('organization_name', ''))}</span></div>
          <div class="detail"><strong>Outcome:</strong> {_v(c.get('documented_outcome', ''))}</div>
          <div class="detail"><strong>Why comparable:</strong> {_v(c.get('comparability_explanation', ''))}</div>
        </div>
        """

    risks_html = ""
    if risks:
        risks_html = '<p><strong>Top Risks:</strong></p><ul>' + "".join(f'<li>{_v(r)}</li>' for r in risks[:3]) + '</ul>'

    return f"""
    <div class="intervention-card{' recommended' if is_recommended else ''}">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <h3>{_v(name)}</h3>
        <div>{tag}</div>
      </div>
      <div style="display:flex;align-items:center;gap:12pt;margin:8pt 0;">
        <div class="{badge_class}">{float(score):.0f}</div>
        <div style="font-size:8pt;color:#667085;">match score</div>
      </div>
      <p style="font-size:9pt;">{_v(rationale)}</p>
      <div style="display:flex;gap:16pt;font-size:8pt;color:#475467;margin:8pt 0;">
        <span><strong>Evidence:</strong> {_v(evidence)}</span>
        <span><strong>Difficulty:</strong> {_v(difficulty)}</span>
        <span><strong>Timeline:</strong> {_v(timeframe)}</span>
      </div>
      <h4 style="font-size:8pt;margin:8pt 0 4pt 0;">Score Breakdown</h4>
      {_score_component_rows(breakdown)}
      {risks_html}
      {f'<h4 style="font-size:8pt;margin:8pt 0 4pt 0;">Comparable Implementations</h4><div class="comparables-grid">{comp_rows}</div>' if comp_rows else ''}
    </div>
    """


def _scored_interventions_section(data: dict) -> str:
    scored = data.get("scored_interventions", [])
    if not scored:
        return ""
    cards = ""
    top_score = scored[0].get("match_score", 0) if scored else 0
    for si in scored:
        is_recommended = si.get("label") == "recommended"
        score = si.get("match_score", 0)
        if not is_recommended and abs(score - top_score) < 5:
            si["rationale"] = (si.get("rationale", "") or "") + " Similarly matched to the top option."
        cards += _intervention_card(si, is_recommended)
    return f"""
    <h2>Recommendations</h2>
    {cards}
    """


def _comparison_view_section(data: dict) -> str:
    scored = data.get("scored_interventions", [])
    if len(scored) < 2:
        return ""
    cols = ""
    for si in scored[:3]:
        cols += f"""
        <div class="comparison-col">
          <h4>{_v(si.get('intervention_name', ''))}</h4>
          <div style="font-size:14pt;font-weight:700;color:#1d2939;">{float(si.get('match_score', 0)):.0f}</div>
          <div class="stat"><div class="stat-label">Impact</div><div class="stat-value">{_v(si.get('expected_impact', ''))[:60]}</div></div>
          <div class="stat"><div class="stat-label">Evidence</div><div class="stat-value">{_v(si.get('evidence_strength', ''))}</div></div>
          <div class="stat"><div class="stat-label">Difficulty</div><div class="stat-value">{_v(si.get('implementation_difficulty', ''))}</div></div>
          <div class="stat"><div class="stat-label">Timeline</div><div class="stat-value">{_v(si.get('estimated_timeframe', ''))}</div></div>
          <div style="margin-top:6pt;"><strong>Advantages:</strong></div>
          <ul style="margin:2pt 0;padding-left:12pt;">{"".join(f'<li>{_v(a)}</li>' for a in si.get('key_advantages', [])[:2])}</ul>
          <div style="margin-top:4pt;"><strong>Tradeoffs:</strong></div>
          <ul style="margin:2pt 0;padding-left:12pt;">{"".join(f'<li>{_v(t)}</li>' for t in si.get('key_tradeoffs', [])[:2])}</ul>
        </div>
        """
    return f"""
    <h2>Comparison</h2>
    <div class="comparison-grid">{cols}</div>
    """


def _exec_summary_section(data: dict) -> str:
    scored = data.get("scored_interventions", [])
    top_si = scored[0] if scored else None
    top_rec = (data.get("recommendations") or [{}])[0]

    if not top_rec and not top_si:
        return "<p>No recommendation available.</p>"

    if top_si:
        name = top_si.get("intervention_name", "")
        score = top_si.get("match_score", 0)
        evidence = top_si.get("evidence_strength", "")
        difficulty = top_si.get("implementation_difficulty", "")
        rationale = top_si.get("rationale", "")
        return f"""
        <div class="summary-box">
          <p><strong>Recommended intervention:</strong> {_v(name)}</p>
          <p><strong>Match score:</strong> {score:.0f}/100</p>
          <p><strong>Evidence:</strong> {_v(evidence)}</p>
          <p><strong>Implementation difficulty:</strong> {_v(difficulty)}</p>
          {f'<p><strong>Why:</strong> {_v(rationale)}</p>' if rationale else ''}
        </div>
        """

    action = top_rec.get("specific_action") or top_rec.get("title", "")
    category = top_rec.get("category", "").replace("_", " ")
    confidence = top_rec.get("confidence", {})
    es = top_rec.get("evidence_summary", {})

    return f"""
    <div class="summary-box">
      <p><strong>Evidence-supported intervention:</strong> {_v(action)}</p>
      <p><strong>Category:</strong> {_v(category)}</p>
      <p><strong>Confidence:</strong> {_pct(confidence.get("score", 0))} ({_v(confidence.get("label", ""))})</p>
      <p><strong>Evidence:</strong> {_v(es.get("total_comparables", 0))} comparable implementations ({_v(es.get("gold_count", 0))} gold, {_v(es.get("silver_count", 0))} silver, {_v(es.get("bronze_count", 0))} bronze)</p>
    </div>
    """


def _outcome_ranges_section(data: dict) -> str:
    top = (data.get("recommendations") or [{}])[0]
    ranges = top.get("outcome_ranges", [])
    if not ranges:
        return ""

    cards = []
    for r in ranges:
        if not r.get("directly_comparable", True):
            continue
        val = ""
        if r.get("calculation_method") == "single_value" and r.get("median") is not None:
            suffix = "%" if r.get("unit") == "%" else ""
            val = f"{r['median']}{suffix}"
        elif r.get("low") is not None and r.get("high") is not None:
            suffix = "%" if r.get("unit") == "%" else ""
            val = f"{r['low']}{suffix} – {r['high']}{suffix}"
        dir_arrow = _direction_emoji(r.get("direction", ""))
        label = r.get("metric_label", "")
        count = r.get("sample_size", 0)
        gold = r.get("gold_count", 0)
        cards.append(f"""
        <div class="outcome-card">
          <div class="value">{dir_arrow} {_v(val)}</div>
          <div class="label">{_v(r.get("direction", ""))} in {_v(label)}</div>
          <div class="count">{count} implementation{'s' if count != 1 else ''}{f', {gold} gold' if gold else ''}</div>
        </div>
        """)

    if not cards:
        return ""

    return f"""
    <h2>Potential Impact Observed</h2>
    <p style="font-size:8.5pt;color:#64748b;margin-bottom:8pt;">Evidence-derived outcome ranges from comparable implementations.</p>
    <div class="outcome-grid">{"".join(cards[:6])}</div>
    """


def _why_ranked_first_section(data: dict) -> str:
    top = (data.get("recommendations") or [{}])[0]
    wrf = top.get("why_ranked_first")
    if not wrf:
        return ""

    parts = [f"    <h2>Why This Path Ranks First</h2>"]

    if wrf.get("summary"):
        parts.append(f"<p>{_v(wrf['summary'])}</p>")

    if wrf.get("supporting_reasons"):
        parts.append("<h3>Supporting reasons</h3><ul>")
        for s in wrf["supporting_reasons"]:
            parts.append(f"<li>{_v(s)}</li>")
        parts.append("</ul>")

    if wrf.get("tradeoffs"):
        parts.append("<h3>Tradeoffs to consider</h3><ul>")
        for t in wrf["tradeoffs"]:
            parts.append(f"<li>{_v(t)}</li>")
        parts.append("</ul>")

    if wrf.get("alternative_differences"):
        parts.append("<h3>Evidence comparison</h3>")
        for alt in wrf["alternative_differences"]:
            reasons = "; ".join(alt.get("reasons", []))
            when = alt.get("when_to_consider", "")
            parts.append(f"""
            <div class="gap-box">
              <h4>vs {_v(alt.get('alternative', ''))}</h4>
              <p>{_v(reasons)}</p>
              {f'<p style="font-style:italic;margin-top:2pt;">{_v(when)}</p>' if when else ''}
            </div>
            """)

    return "".join(parts)


def _alternative_comparison_section(data: dict) -> str:
    recs = data.get("recommendations", [])
    if len(recs) < 1:
        return ""

    rows = []
    for r in recs:
        ac = r.get("alternative_comparison") or {}
        rows.append(f"""
        <tr>
          <td><strong>{_v(r.get('title', ''))}</strong></td>
          <td>{_v(ac.get('evidence_strength', ''))}</td>
          <td>{_v(ac.get('outcome_support', ''))}</td>
          <td>{_v(ac.get('implementation_complexity', ''))}</td>
          <td>{_v(ac.get('expected_timeline', ''))}</td>
          <td>{_v(ac.get('reason_for_rank', ''))}</td>
        </tr>
        """)

    if not rows:
        return ""

    return f"""
    <h2>Other Paths Evaluated</h2>
    <table>
      <tr><th>Intervention</th><th>Evidence</th><th>Outcome support</th><th>Complexity</th><th>Timeline</th><th>Why ranked here</th></tr>
      {''.join(rows)}
    </table>
    """


def _comparables_section(data: dict) -> str:
    top = (data.get("recommendations") or [{}])[0]
    comparables = top.get("comparable_implementations", [])
    if not comparables:
        return ""

    cards = []
    for c in comparables[:8]:
        tier = c.get("evidence_tier", "bronze").lower()
        tier_cls = {"gold": "tier-gold", "silver": "tier-silver"}.get(tier, "tier-bronze")
        cards.append(f"""
        <div class="comparable-card">
          <div class="header">
            <span class="org">{_v(c.get('organization', ''))}</span>
            <span class="{tier_cls}">{tier.upper()}</span>
          </div>
          {f'<div class="detail"><strong>Workflow:</strong> {_v(c.get("workflow_context", ""))}</div>' if c.get('workflow_context') else ''}
          {f'<div class="detail"><strong>Intervention:</strong> {_v(c.get("intervention", ""))[:120]}</div>' if c.get('intervention') else ''}
          <div class="detail"><strong>Result:</strong> {_v(c.get("outcome_summary", ""))}</div>
          <div class="detail"><strong>Relevance:</strong> {_v(c.get("relevance_explanation", ""))}</div>
          {f'<div class="limitation">Note: {_v(c.get("limitations", ""))}</div>' if c.get('limitations') else ''}
        </div>
        """)

    return f"""
    <h2>Comparable Implementations</h2>
    <div class="comparables-grid">{"".join(cards)}</div>
    """


def _risks_section(data: dict) -> str:
    top = (data.get("recommendations") or [{}])[0]
    risks = top.get("risks", [])
    if not risks:
        return ""

    boxes = []
    for r in risks[:4]:
        boxes.append(f"""
        <div class="risk-box">
          <h4>{_v(r.get('title', r.get('category', 'Risk')))}</h4>
          <p>{_v(r.get('explanation', r.get('risk', '')))}</p>
          {f'<p class="mitigation">Mitigation: {_v(r.get("mitigation", ""))}</p>' if r.get('mitigation') else ''}
        </div>
        """)

    return f"""
    <h2>Risk Assessment</h2>
    <div>{"".join(boxes)}</div>
    """


def _assumptions_gaps_section(data: dict) -> str:
    rec = (data.get("recommendations") or [{}])[0]
    assumptions = rec.get("assumptions_detail", []) or data.get("assumptions", [])
    gaps = rec.get("information_gaps", []) or data.get("information_gaps", [])
    if not assumptions and not gaps:
        return ""

    parts = [f'<div class="page-break"></div><h2>Assumptions and Information Gaps</h2>']

    if assumptions:
        parts.append("<h3>Assumptions made</h3>")
        for a in assumptions[:4]:
            parts.append(f"""
            <div class="gap-box">
              <h4>{_v(a.get('title', ''))}</h4>
              <p>{_v(a.get('explanation', ''))}</p>
              {f'<p style="font-size:7.5pt;color:#94a3b8;margin-top:2pt;">Effect: {_v(a.get("effect_on_recommendation", ""))}</p>' if a.get('effect_on_recommendation') else ''}
            </div>
            """)

    if gaps:
        parts.append("<h3>Information that would improve this analysis</h3>")
        for g in gaps[:4]:
            parts.append(f"""
            <div class="gap-box">
              <h4>{_v(g.get('title', ''))}</h4>
              <p>{_v(g.get('explanation', ''))}</p>
              {f'<p style="font-size:7.5pt;color:#94a3b8;margin-top:2pt;">Resolution: {_v(g.get("resolution_action", ""))}</p>' if g.get('resolution_action') else ''}
            </div>
            """)

    return "".join(parts)


def _next_step_section(data: dict) -> str:
    rec = (data.get("recommendations") or [{}])[0]
    ns = rec.get("next_validation_step") or {}
    if not ns.get("action"):
        return ""

    return f"""
    <div class="next-box">
      <h3>Next Step</h3>
      <p><strong>{_v(ns.get('action', ''))}</strong></p>
      {f'<p>Purpose: {_v(ns.get("purpose", ""))}</p>' if ns.get('purpose') else ''}
      {f'<p class="detail">Owner: {_v(ns.get("owner", ""))} | Duration: {_v(ns.get("duration", ""))}</p>' if ns.get('owner') or ns.get('duration') else ''}
      {f'<p class="detail">Success: {_v(ns.get("success_criteria", ""))}</p>' if ns.get('success_criteria') else ''}
      {f'<p class="detail">Decision enabled: {_v(ns.get("decision_enabled", ""))}</p>' if ns.get('decision_enabled') else ''}
    </div>
    """


def _methodology_section(data: dict) -> str:
    method = data.get("methodology_summary", "")
    if not method:
        return ""
    return f"""
    <h2>Methodology</h2>
    <p style="font-size:8.5pt;">{_v(method)}</p>
    <p style="font-size:8pt;color:#64748b;margin-top:4pt;">
      Engine version: {_v(data.get('engine_version', ''))} |
      Dataset: {_v(data.get('dataset_version', ''))} |
      Generated: {_v(data.get('generated_at', '')).split('.')[0].replace('T', ' ')} UTC
    </p>
    """


def generate_report_html(data: dict) -> str:
    top = (data.get("recommendations") or [{}])[0]
    action = top.get("specific_action") or top.get("title", "Recommendation")
    category = top.get("category", "").replace("_", " ")
    generated = data.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        date_str = dt.strftime("%B %d, %Y")
    except Exception:
        date_str = generated.split("T")[0] if "T" in generated else generated

    problem = data.get("assessment_summary", {}).get("problem_statement", "")
    workflow = data.get("assessment_summary", {}).get("workflow", "").replace("_", " ")
    scored = data.get("scored_interventions", [])

    has_new_system = len(scored) > 0

    if has_new_system:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Compass — Recommendation Report</title>{_STYLES}</head><body>

<div class="logo">Compass</div>
<div class="meta">
  <span>Prepared: {_v(date_str)}</span>
  <span>Workflow: {_v(workflow)}</span>
  <span>Engine: {_v(data.get('engine_version', ''))} | Dataset: {_v(data.get('dataset_version', ''))}</span>
</div>

<h1>Executive Summary</h1>
{_exec_summary_section(data)}

{_scored_interventions_section(data)}

{_comparison_view_section(data)}

<div class="page-break"></div>
<h2>Comparable Implementations</h2>
{_comparables_section(data)}

<h2>Risk Assessment</h2>
{_risks_section(data)}

{_assumptions_gaps_section(data)}

<h2>Next Step</h2>
{_next_step_section(data)}

{_methodology_section(data)}

<div class="footer-note">
  This report was generated from the Compass evidence graph. Recommendations are based on multi-component scoring including problem alignment, organizational similarity, goal alignment, evidence strength, implementation fit, and outcome consistency. Findings are based on comparable real-world implementations and the information provided during assessment.
</div>

</body></html>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Compass — Recommendation Report</title>{_STYLES}</head><body>

<div class="logo">Compass</div>
<div class="meta">
  <span>Prepared: {_v(date_str)}</span>
  <span>Workflow: {_v(workflow)}</span>
  <span>Intervention category: {_v(category)}</span>
  <span>Engine: {_v(data.get('engine_version', ''))} | Dataset: {_v(data.get('dataset_version', ''))}</span>
</div>

<h1>Executive Summary</h1>
{_exec_summary_section(data)}

<div class="page-break"></div>
<h2>Primary Recommendation</h2>
{_outcome_ranges_section(data)}
{_why_ranked_first_section(data)}

<h2>Comparable Implementations</h2>
{_comparables_section(data)}

<div class="page-break"></div>
<h2>Alternatives</h2>
{_alternative_comparison_section(data)}

<h2>Risk Assessment</h2>
{_risks_section(data)}

<h2>Assumptions &amp; Information Gaps</h2>
{_assumptions_gaps_section(data)}

<h2>Next Step</h2>
{_next_step_section(data)}

{_methodology_section(data)}

<div class="footer-note">
  This report was generated from the Compass evidence graph. Findings are based on comparable real-world implementations and the information provided during assessment. Outcomes observed in comparable organizations do not guarantee identical results.
</div>

</body></html>"""


def generate_report_pdf(data: dict) -> Optional[bytes]:
    html = generate_report_html(data)
    try:
        import weasyprint
        pdf_bytes = weasyprint.from_string(html)
        logger.info(f"Generated PDF ({len(pdf_bytes)} bytes)")
        return pdf_bytes
    except ImportError:
        logger.warning("weasyprint not available — returning None")
        return None
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None
