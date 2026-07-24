import json
import hashlib
from datetime import datetime

import requests


LLM_EXTRACTION_PROMPT = """You classify operational intervention evidence for Compass.

FIRST, classify into ONE tier:
- tier1 (GOLD): Real org implementation with measured outcomes. Has: named org, operational problem, deployed intervention, before/after metrics.
- tier2 (SILVER): Industry research/benchmarks (McKinsey, Gartner, surveys with aggregate stats).
- tier3 (BRONZE): Academic paper proposing novel method/algorithm (no real org deployed it).
- rejected: News without implementation evidence, opinions, product announcements without outcomes.

If rejected/tier3: ONLY output {"evidence_tier": "tier1/2/3/rejected", "rejection_reason": "..."} — nothing else.

If tier1: Output ALL fields below. Exact JSON. No markdown.
{
  "evidence_tier": "tier1",
  "organization_name": "...",
  "organization_type": "company/government/healthcare/nonprofit/startup/enterprise/academic",
  "organization_industry": ["healthcare", "finance", "manufacturing", "retail", "technology", "energy", "government"],
  "organization_employee_count": null,
  "organization_annual_revenue": null,
  "business_problem": "operational problem, NOT technical",
  "business_function": "sales/marketing/customer_support/finance/hr/it/engineering/operations/supply_chain/legal/compliance/product/research",
  "workflow": "specific process like invoice processing",
  "intervention_title": "...",
  "intervention_category": "AI/Software/Workflow_Automation/Process_Redesign/Staffing/Hybrid",
  "intervention_subcategories": ["rpa", "cloud_migration", "lean", "training"],
  "intervention_software": [],
  "intervention_vendors": [],
  "teams_involved": ["IT", "operations"],
  "pilot_used": false,
  "alternatives_considered": [],
  "baseline_description": "before state",
  "baseline_metrics": [{"metric_name": "...", "value": 100, "unit": "hours"}],
  "implementation_status": "completed/in_progress/abandoned/planned",
  "implementation_duration_value": null, "implementation_duration_unit": "weeks/months",
  "implementation_cost_value": null, "implementation_cost_currency": "USD",
  "measurement_period_value": null, "measurement_period_unit": "months",
  "outcomes": [{"metric_name": "...", "category": "time/cost/revenue/quality/satisfaction/adoption/risk", "baseline_value": null, "post_value": null, "absolute_change": null, "percentage_change": null, "direction": "positive/negative/neutral", "unit": "", "value_type": "observed/projected/estimated", "source_passage": "exact quote"}],
  "result_summary": "one sentence",
  "success_factors": [], "failure_conditions": [], "challenges": [], "lessons_learned": [], "unintended_consequences": [],
  "evidence_quality": {"is_vendor_reported": false, "independently_verified": null, "has_control_group": null, "sample_size": null, "source_credibility": "high/medium/low"},
  "source_passages": [{"field": "outcome", "passage": "exact quote"}],
  "extraction_notes": ""
}

If tier2: Output {"evidence_tier": "tier2", "organizations_studied": [], "aggregate_statistics": "", "source_name": "", "evidence_notes": ""}

SOURCE TEXT BELOW — classify and extract:
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
