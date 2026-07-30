import json
import hashlib
from datetime import datetime

import requests


LLM_EXTRACTION_PROMPT = """You are a research analyst extracting structured operational transformation records from business case studies for Compass.

Extract EVERY implementation detail present in the text. If a value is mentioned ANYWHERE in the text, extract it — do NOT leave it null.

FIRST, classify into ONE evidence tier:
- GOLD: Named organization with a REAL deployed intervention and MEASURED QUANTIFIED outcomes (percentages, dollar amounts, time reductions). Has baseline and post-implementation data.
- SILVER: Named organization with a real deployed intervention and described outcomes (could be qualitative). Lacks quantified before/after comparison.
- BRONZE: Named organization with an intervention but limited outcome detail. Industry research with aggregate statistics.
- rejected: No real implementation. Opinions, product announcements without outcomes, generic news, hypothetical use cases.

For GOLD and SILVER, extract EVERY field below. Do NOT leave fields null — use "" for text and 0 for numbers if not found. But if the text CONTAINS a value, you MUST extract it.

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
  "evidence_quality": {
    "is_vendor_reported": true/false,
    "independently_verified": true/false (true if source is a news article, government report, academic paper, or independent publication; false if vendor marketing or customer story on vendor site),
    "source_credibility": "high/medium/low"
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
