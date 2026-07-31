import json
import hashlib
from datetime import datetime

import requests


LLM_EXTRACTION_PROMPT = """You are a research analyst extracting structured operational transformation records from business case studies for Compass.

Extract EVERY implementation detail present in the text. If a value is mentioned ANYWHERE in the text, extract it — do NOT leave it null.

FIRST, classify implementation detail and outcome credibility SEPARATELY, along with a single combined tier.

IMPLEMENTATION EVIDENCE PROVENANCE (how well is the implementation documented):
- vendor_documented: Named organization with implementation described by a vendor (e.g., vendor case study). Implementation steps, timeline, architecture may be detailed. HIGH signal for implementation detail, LOWER signal for outcome claims.
- customer_documented: Named organization with implementation described by the customer themselves (e.g., engineering blog, conference talk). HIGH signal for both implementation detail and outcome claims.
- independently_validated: Implementation described by a third party (e.g., news article, analyst report, non-vendor publication). HIGH signal for outcome credibility.
- government_audited: Implementation audited by a government accountability office (GAO, NAO, etc.). HIGHEST signal for outcome credibility.
- peer_reviewed: Implementation described in a peer-reviewed academic paper, journal, or conference proceeding. HIGH signal for both implementation detail and outcomes.
- financial_disclosure: Implementation disclosed in SEC filings (10-K, 10-Q) or annual reports. HIGH signal for organizational impact and financial outcomes.

OUTCOME EVIDENCE PROVENANCE (how credible are the outcome claims):
- vendor_reported: Outcomes reported by the vendor selling the solution. Credibility is lower — treated as directional.
- independently_verified: Outcomes verified by a non-vendor source (news, government report, audit, academic paper).
- peer_reviewed_methodology: Outcomes measured using peer-reviewed methodology (controlled study, rigorous pre/post comparison).
- government_audited_outcomes: Outcomes verified through independent government audit.

COMBINED EVIDENCE TIER (for backward compatibility):
- GOLD: High-confidence CAUSAL implementation evidence. At least ONE of:
    * Government audit (GAO/NAO/etc.) documenting an implementation with measured outcomes and explicit baseline vs post-implementation comparison.
    * Public company SEC filing (10-K, 10-Q, 8-K) or annual report disclosing quantified business outcomes of an implementation (cost savings, productivity, processing time) with material detail.
    * Peer-reviewed implementation study with quantified outcomes and described methodology (sample, time period, measurement approach).
    * Randomized controlled trial, quasi-experimental, or independent-evaluator study with measured causal effect.
  Must have BOTH a named organization (or clearly identified program/system) AND measured quantified outcomes (baseline and post values, or a documented percentage change). Financial disclosures of large-scale initiatives count even if the "baseline" is described in prose rather than as a numeric value, as long as the change is quantified.
- SILVER: Named organization with a real deployed intervention and described outcomes. Source is independently validated, customer-documented, or financial disclosure WITHOUT full quantified before/after comparison. High implementation detail but outcome claims not fully measured.
- BRONZE: Vendor_documented implementation with named organization and real deployment, but outcomes may be self-reported or unquantified.
- rejected: No real implementation. Opinions, product announcements without outcomes, generic news, hypothetical use cases.

For all accepted tiers (GOLD, SILVER, BRONZE), extract EVERY field below. Do NOT leave fields null — use "" for text and 0 for numbers if not found. But if the text CONTAINS a value, you MUST extract it.

REQUIRED: Extract the following fields with priority. If the text mentions any of these, you MUST include them:

OUTPUT JSON:
{
  "organization_name": "extracted company/organization name",
  "organization_industry": "MUST extract industry from text. Look for: industry sector, company description, vertical market. Common values: healthcare, finance, banking, insurance, manufacturing, retail, technology, telecommunications, energy, government, education, logistics, transportation, hospitality, media, agriculture, pharmaceuticals, construction, aerospace, automotive, professional_services, nonprofit. Choose the SINGLE best match.",
  "organization_employee_count": EXACT NUMBER IF MENTIONED, else 0,
  "business_problem": "specific operational problem being solved",
  "business_function": "MUST extract. Options: sales, marketing, customer_support, finance, hr, it, engineering, operations, supply_chain, legal, compliance, product, procurement, research. Choose ONE best match.",
  "workflow": "specific workflow or process name",
  "intervention_title": "what was actually implemented or deployed",
  "intervention_category": "ONE of: Workflow_Automation, AI, Software, Process_Redesign, Staffing, Hybrid",
  "intervention_subcategories": ["list of specific technology/approach categories"],
  "intervention_vendors": ["list of vendor/product names if mentioned"],
  "baseline_description": "what was happening before",
  "implementation_status": "completed/in_progress/abandoned",
  "implementation_duration_value": EXACT NUMBER IF MENTIONED, else 0,
  "implementation_duration_unit": "weeks/months/years/days" if duration mentioned,
  "implementation_partner": ["Accenture", "McKinsey", "Deloitte", ...] IF implementation partners are mentioned (consulting firms, system integrators, agencies that helped implement),
  "implementation_pattern": ["Pilot → Department Rollout", "Internal Champion → Executive Sponsor → Cross-functional Team", "Big Bang Deployment", "Phased Migration", "Greenfield Build", "Lift and Shift", "Hybrid Cloud Migration", "Center of Excellence", ...] Choose the pattern(s) that best match the described rollout approach,
  "lessons_learned": ["key lessons extracted from the text about what worked, what failed, what they would do differently"],
  "change_management": "description of the change management approach: training, communication, stakeholder buy-in, resistance handling, culture change",
  "rollout_strategy": "step-by-step description of how the implementation was rolled out: phases, timelines, teams, geographic/org sequencing",
  "governance_model": "governance structure: steering committee, PMO, executive sponsor, cross-functional governance, vendor-led, internal COE, etc.",
  "executive_sponsor": "name or title of the executive sponsor who championed this implementation (e.g. 'CIO', 'VP of Operations', 'CFO')",
  "pilot_structure": "description of the pilot: scope, duration, team size, success criteria, whether it was a proof-of-concept or formal pilot",
  "training_approach": "how users were trained: workshops, self-paced, train-the-trainer, vendor-led, embedded coaches, etc.",
  "adoption_approach": "how adoption was driven: incentives, gamification, executive mandate, phased rollout, power users/champions",
  "implementation_team_structure": "composition of implementation team: internal FTEs, contractor mix, dedicated vs part-time, cross-functional vs siloed",
  "budget_range": "approximate budget if mentioned (e.g. '$500K-$1M', '$2M+', '<$100K')",
  "key_decision_makers": ["CIO", "CFO", "VP Operations", ...] — roles of key decision makers involved",
  "success_criteria": ["reduced processing time by 50%", "ROI > 200%", "user adoption > 80%", ...] — what defined success for this implementation",
  "outcomes": [
    {
      "metric_name": "specific metric name",
      "category": "time/cost/revenue/quality/satisfaction/adoption/efficiency/productivity",
      "baseline_value": NUMBER IF MENTIONED,
      "post_value": NUMBER IF MENTIONED,
      "absolute_change": NUMBER IF MENTIONED,
      "percentage_change": NUMBER IF MENTIONED (e.g. 30 for 30%%),
      "unit": "percent/hours/dollars/points/FTE/etc",
      "direction": "positive/negative",
      "value_type": "observed/projected/estimated",
      "source_passage": "EXACT QUOTE from the text supporting this metric"
    }
  ],
  "result_summary": "one sentence summary of what happened",
  "outcome_block": {
    "baseline_metric": "the measured value or state BEFORE the implementation, with units (e.g. '12 days average claims processing time', '4.2%% fulfillment cost')",
    "post_metric": "the measured value or state AFTER the implementation, with units",
    "percent_change": NUMBER (percent change from baseline to post, e.g. 67 for a reduction of 12 to 4 days), OR null,
    "time_period": "measurement window, e.g. '6 months after deployment'",
    "organization": "organization where the outcome was measured",
    "implementation": "brief description of what was implemented that produced the outcome",
    "measurement_method": "how the outcome was measured (company-reported financials, government audit, controlled study, operational system data, customer survey, etc.)",
    "confidence": "high/medium/low (high = baseline+post both measured, medium = one measured one estimated, low = both estimated or anecdotal)",
    "source_type": "sec_filing/earnings_call/annual_report/vendor_case_study/government_audit/academic_paper/company_blog",
    "evidence_level": "causal/strong_correlation/correlational/directional (causal = controlled study or audited pre/post, strong_correlation = clear pre/post with controls, correlational = pre/post without controls, directional = qualitative claim without measured change)"
  },
  "evidence_quality": {
    "is_vendor_reported": true/false,
    "independently_verified": true/false,
    "source_credibility": "high/medium/low",
    "implementation_detail_score": 1-10 (how thoroughly is the implementation approach documented: architecture, timeline, stakeholders, roll-out steps, integrations, change management),
    "outcome_credibility_score": 1-10 (how credible are the outcome claims: independently verified > customer-reported > vendor-reported),
    "methodology_detail_score": 1-10 (how well is the measurement methodology described: baseline vs post-implementation, sample sizes, time periods, statistical methods),
    "operational_insight_score": 1-10 (how much operational detail is present: team structure, governance, budget, organizational context, challenges encountered, lessons learned),
    "implementation_provenance": "vendor_documented/customer_documented/independently_validated/government_audited/peer_reviewed/financial_disclosure",
    "outcome_provenance": "vendor_reported/independently_verified/peer_reviewed_methodology/government_audited_outcomes"
  }
}

If the text is not about a real operational transformation implementation, respond: {"evidence_tier": "rejected", "rejection_reason": "brief reason"}

SOURCE TEXT:
"""


class LLMExtractor:

    def __init__(self, api_key: str, model: str = "deepseek-v4-flash",
                 endpoint: str = "https://api.deepseek.com", temperature: float = 0.0):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.temperature = temperature
        self.stats = {"total_calls": 0, "total_input_tokens": 0,
                      "total_output_tokens": 0, "total_cost": 0.0, "errors": 0}
        self.cache = {}

    def get_cost_per_token(self) -> tuple:
        if "deepseek" in self.model.lower():
            return 0.00000014, 0.00000056  # input, output per token (DeepSeek V3 prices)
        return 0.000001, 0.000002  # fallback

    def extract(self, text: str, title: str = "", url: str = "",
                max_text_length: int = 8000, use_cache: bool = True) -> dict:
        cache_key = hashlib.sha256(text.encode()).hexdigest()
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key]

        prompt = LLM_EXTRACTION_PROMPT + "\n\n" + (text[:max_text_length] or "")
        self.stats["total_calls"] += 1

        try:
            resp = requests.post(
                f"{self.endpoint}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                    "max_tokens": 8192,
                    # DeepSeek doesn't support response_format json_object
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

            input_tokens = data["usage"]["prompt_tokens"]
            output_tokens = data["usage"]["completion_tokens"]
            input_cost, output_cost = self.get_cost_per_token()
            cost = (input_tokens * input_cost) + (output_tokens * output_cost)

            self.stats["total_input_tokens"] += input_tokens
            self.stats["total_output_tokens"] += output_tokens
            self.stats["total_cost"] += cost

            content = data["choices"][0]["message"]["content"]
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            result = json.loads(content)
            result["_meta"] = {
                "model": self.model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "extracted_at": datetime.utcnow().isoformat(),
            }
            self.cache[cache_key] = result
            return result

        except Exception as e:
            self.stats["errors"] += 1
            return {
                "has_intervention": False,
                "_meta": {"error": str(e), "model": self.model,
                          "extracted_at": datetime.utcnow().isoformat()},
                "extraction_notes": f"Extraction failed: {e}"
            }

    def extract_batch(self, documents: list[dict], batch_size: int = 5,
                      max_text_length: int = 8000) -> list[dict]:
        results = []
        for doc in documents:
            text = doc.get("text", doc.get("cleaned_text", ""))
            if not text and doc.get("title"):
                text = doc["title"]
            if not text or len(text.strip()) < 100:
                results.append({
                    "document_id": doc.get("id"),
                    "title": doc.get("title", "")[:100],
                    "url": doc.get("url", ""),
                    "extraction": {"has_intervention": False,
                                   "extraction_notes": "Insufficient source text (<100 chars)"}
                })
                continue
            result = self.extract(text, doc.get("title"), doc.get("url"), max_text_length)
            results.append({
                "document_id": doc.get("id"),
                "title": doc.get("title", "")[:100],
                "url": doc.get("url", ""),
                "extraction": result,
            })
        return results

    def usage_report(self) -> dict:
        return dict(self.stats)
