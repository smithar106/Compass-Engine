"""V3 LLM extractor module — shared between extraction scripts."""

import json, hashlib
from datetime import datetime
import requests

V3_EXTRACTION_PROMPT = """You are Compass Evidence Extractor V3. You classify operational implementation evidence.

FIRST, classify into exactly ONE tier:

TIER 1 — Gold: Real organization implementation at a named organization with:
  - Named organization (company, government agency, non-profit)
  - Operational business problem (not technical-only)
  - Deployed intervention (AI, software, process redesign, automation, staffing, etc.)
  - Measurable outcome with before/after data (quantified metric)
  - Implementation completed or in progress with results
  Example: "Acme Corp deployed AI chatbots for customer support and reduced handle time by 40%"

TIER 2 — Silver: Real implementation with clear intervention and outcome, but:
  - Missing one supporting attribute (e.g., org name anonymized, outcome estimated not observed)
  - OR industry bench research with named orgs and aggregate statistics
  OR: Implementation exists but incomplete evidence (e.g., pilot, no baseline)
  Example: "A large retailer implemented RPA for AP automation saving 15,000 hours/year" (org anonymized)

TIER 3 — Bronze: Supporting evidence that is useful but not a full case study:
  - Academic paper describing a real deployment at a named organization (NOT synthetic benchmarks)
  - Industry report with implementation details
  - Benchmark study with named orgs
  - Survey with quantified outcomes from real deployments
  - NOT: pure academic method papers without deployment
  Example: "Case study published in Journal of Operations Management: Siemens reduced lead time 35% using Lean"

REJECTED — No evidence value:
  - Reddit auth pages, login walls
  - Personal/hobby projects (no real org)
  - Product announcements without outcomes
  - News/opinion without implementation data
  - Press releases without results
  - Vendor landing pages without evidence
  - SEO spam, listicles
  - Conference recaps
  - Duplicate syndicated content
  - Pages with insufficient content (<100 chars readable)

OUTPUT FORMAT — follow exactly based on tier:

If REJECTED:
{"evidence_tier": "rejected", "rejection_reason": "Short explanation", "document_type": "news|opinion|product_page|personal_project|login_page|seo_spam|duplicate|insufficient_content"}

If TIER 3:
{"evidence_tier": "tier3", "evidence_type": "academic_deployment|industry_report|benchmark_study|survey", "organizations_mentioned": ["Org1", "Org2"], "workflows_mentioned": ["workflow1"], "summary": "Brief summary of the evidence value", "source_credibility": "high|medium|low", "extraction_notes": ""}

If TIER 2:
{"evidence_tier": "tier2", "missing_attribute": "organization_name|baseline_metrics|outcome_quantification|implementation_status", "organization_name": "Org Name or null if anonymized", "organization_type": "company|government|healthcare|nonprofit|startup|enterprise|academic", "organization_industry": ["healthcare", "finance", ...], "business_problem": "Operational problem description", "business_function": "sales|marketing|customer_support|finance|hr|it|engineering|operations|supply_chain|legal|compliance|procurement|product", "workflow": "Specific process", "intervention_title": "Name of intervention", "intervention_category": "AI|Software|Workflow_Automation|Process_Redesign|Staffing|Outsourcing|Hybrid", "intervention_software": [], "intervention_vendors": [], "implementation_status": "completed|in_progress|pilot|planned|unknown", "outcome_summary": "What happened", "outcome_metrics": [{"metric_name": "handle_time", "value": 40, "unit": "percent", "direction": "positive|negative|neutral", "value_type": "observed|estimated|projected"}], "evidence_quality": {"is_vendor_reported": false, "independently_verified": null}, "source_passages": [{"field": "outcome", "passage": "Exact quote"}]}

If TIER 1:
{"evidence_tier": "tier1", "organization_name": "Full legal name", "organization_type": "company|government|healthcare|nonprofit|startup|enterprise", "organization_industry": ["industry"], "organization_employee_count": null, "organization_country": null, "business_problem": "Operational problem (not technical)", "business_function": "function", "workflow": "Specific process name", "intervention_title": "Intervention name", "intervention_category": "AI|Software|Workflow_Automation|Process_Redesign|Staffing|Outsourcing|Hybrid", "intervention_subcategories": ["rpa", "lean", "cloud_migration", "training", ...], "intervention_software": ["Software1"], "intervention_vendors": ["Vendor1"], "teams_involved": ["IT", "operations"], "pilot_used": false, "alternatives_considered": [], "baseline_description": "Before state description", "baseline_metrics": [{"metric_name": "...", "value": 100, "unit": "hours"}], "implementation_status": "completed|in_progress", "implementation_duration_value": null, "implementation_duration_unit": "weeks|months", "implementation_cost_value": null, "implementation_cost_currency": "USD", "measurement_period_value": null, "measurement_period_unit": "months", "outcomes": [{"metric_name": "...", "category": "time|cost|revenue|quality|satisfaction|adoption|risk", "baseline_value": null, "post_value": null, "absolute_change": null, "percentage_change": null, "direction": "positive|negative|neutral", "unit": "", "value_type": "observed|estimated|projected", "source_passage": "Exact quote from article"}], "result_summary": "One sentence summary", "success_factors": [], "failure_conditions": [], "challenges": [], "lessons_learned": [], "unintended_consequences": [], "evidence_quality": {"is_vendor_reported": false, "independently_verified": null, "has_control_group": null, "sample_size": null, "source_credibility": "high|medium|low"}, "source_passages": [{"field": "outcome", "passage": "Exact quote"}], "extraction_notes": ""}

SOURCE TEXT BELOW — classify and extract:
"""


class V3Extractor:

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
            return 0.00000014, 0.00000056
        return 0.000001, 0.000002

    def extract(self, text: str, title: str = "", url: str = "",
                max_text_length: int = 8000, use_cache: bool = True) -> dict:
        cache_key = hashlib.sha256(text.encode()).hexdigest()
        if use_cache and cache_key in self.cache:
            return self.cache[cache_key]

        source_block = f"Title: {title}\nURL: {url}\n\n{text[:max_text_length]}"
        prompt = V3_EXTRACTION_PROMPT + "\n\n" + source_block
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
                "evidence_tier": "rejected",
                "rejection_reason": f"Extraction failed: {e}",
                "document_type": "insufficient_content",
                "_meta": {"error": str(e), "model": self.model,
                          "extracted_at": datetime.utcnow().isoformat()},
            }

    def usage_report(self) -> dict:
        return dict(self.stats)
