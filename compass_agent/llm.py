"""Cost-aware LLM client for enrichment.

Wraps DeepSeek / Anthropic chat-completions and estimates spend *before* each
call so the daemon can enforce budget ceilings without burning budget first.
The extraction prompt is reused from ``compass_collector.extraction_llm`` so
the agent produces the same field contract as the engine's batch pipeline.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from compass_collector.extraction_llm.llm_extractor import LLM_EXTRACTION_PROMPT

log = logging.getLogger("compass_agent.llm")

# Per-token USD pricing. DeepSeek V3 pricing mirrors llm_extractor; Anthropic
# defaults to a conservative Sonnet-class rate.
PRICING: dict[str, dict[str, float]] = {
    "deepseek": {"input": 0.00000014, "output": 0.00000056},
    "anthropic": {"input": 0.000003, "output": 0.000015},
}

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "anthropic": "claude-sonnet-4-20250514",
}

# Conservative output-token budget for a structured extraction call.
DEFAULT_OUTPUT_TOKENS = 2500

MULTI_EXTRACTION_PROMPT = """You are a research analyst extracting evidence-driven business interventions for Compass, a Decision Intelligence Engine.

The text below may describe MULTIPLE organizations that implemented operational interventions with measured outcomes (case studies, ROI reports, transformation roundups).

Extract a JSON ARRAY — one object per implementation that has a named organization AND a described intervention. Each object:
{
  "organization_name": "company or org name",
  "organization_industry": "canonical industry (e.g. financial_services, healthcare, retail_consumer, technology, manufacturing)",
  "workflow": "specific workflow or process",
  "intervention_title": "what was implemented",
  "intervention_category": "Workflow_Automation | AI | Software | Process_Redesign | Staffing | Hybrid",
  "evidence_tier": "gold | silver | bronze | rejected",
  "rollout_strategy": "how it was rolled out",
  "success_criteria": ["validation gates / success measures"],
  "lessons_learned": ["lessons"],
  "implementation_pattern": ["Pilot -> Rollout", ...],
  "outcomes": [{"metric_name": "...", "category": "time/cost/revenue/quality/...", "percentage_change": number, "unit": "..."}]
}

Only include items with a real organization and a concrete intervention. Be
generous: include bronze-level implementations (vendor-reported, partial
outcomes) — a named organization + a described intervention is enough. Skip
generic mentions without a specific organization or intervention. Return [] only
if the text truly describes no implementations.

SOURCE TEXT:
"""


@dataclass
class EnrichmentResult:
    payload: dict
    cost: float
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient:
    """Provider-agnostic enrichment client with per-call cost estimation."""

    def __init__(
        self,
        api_key: str = "",
        provider: str = "deepseek",
        model: str = "",
        concurrency: int = 2,
        timeout: float = 120.0,
        http: Optional[httpx.Client] = None,
    ) -> None:
        self.api_key = api_key
        self.provider = provider.lower()
        self.model = model or DEFAULT_MODELS.get(self.provider, "deepseek-chat")
        self.concurrency = max(1, concurrency)
        self.timeout = timeout
        self._http = http
        self._lock = threading.Lock()
        self._spent = 0.0

    # -- config ------------------------------------------------------------
    @property
    def can_run(self) -> bool:
        return bool(self.api_key)

    @property
    def prices(self) -> dict[str, float]:
        return PRICING.get(self.provider, PRICING["deepseek"])

    # -- estimation --------------------------------------------------------
    def estimate_input_tokens(self, text: str) -> int:
        # ~4 chars/token is a safe heuristic.
        return max(1, len(text or "") // 4)

    def estimate_cost(self, text: str) -> float:
        if not self.can_run:
            return 0.0
        tokens_in = self.estimate_input_tokens(text)
        tokens_out = DEFAULT_OUTPUT_TOKENS
        p = self.prices
        return tokens_in * p["input"] + tokens_out * p["output"]

    # -- calls -------------------------------------------------------------
    def enrich(self, text: str, title: str = "", url: str = "") -> EnrichmentResult:
        """Extract structured enrichment from source text via the LLM."""
        if not self.can_run:
            raise RuntimeError("LLM client has no API key configured")
        prompt = LLM_EXTRACTION_PROMPT + "\n\n" + (text or "")[:8000]
        endpoint = self._endpoint()
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 8192,
        }
        headers = {"Content-Type": "application/json"}
        if self.provider == "deepseek":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
            body["max_tokens"] = 8192

        http = self._http or httpx.Client(timeout=self.timeout)
        try:
            resp = http.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            usage = data.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            output_tokens = int(
                usage.get("completion_tokens") or usage.get("output_tokens") or 0
            )
            cost = self._compute_cost(input_tokens, output_tokens)
            payload = self._parse_json(content)
            payload.setdefault("_meta", {}).update(
                {
                    "model": self.model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "title": title,
                    "url": url,
                }
            )
            with self._lock:
                self._spent += cost
            return EnrichmentResult(
                payload=payload,
                cost=cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self.model,
            )
        except Exception as exc:  # network / HTTP / JSON errors
            log.error("LLM enrich failed: %s", exc)
            payload = {
                "evidence_tier": "rejected",
                "rejection_reason": f"extraction_failed: {exc}",
                "_meta": {"model": self.model, "error": str(exc),
                          "extracted_at": datetime.now(timezone.utc).isoformat()},
            }
            return EnrichmentResult(
                payload=payload, cost=0.0, input_tokens=0,
                output_tokens=0, model=self.model,
            )

    def _endpoint(self) -> str:
        if self.provider == "anthropic":
            return "https://api.anthropic.com/v1/messages"
        return "https://api.deepseek.com/v1/chat/completions"

    def enrich_many(self, text: str, title: str = "", url: str = "") -> "list[EnrichmentResult]":
        """Extract MULTIPLE implementations from a roundup/summary page.

        Returns one EnrichmentResult per implementation found (empty list when
        the page describes none). Cost is attributed to each result.
        """
        if not self.can_run:
            return []
        prompt = MULTI_EXTRACTION_PROMPT + "\n\n" + (text or "")[:8000]
        endpoint = self._endpoint()
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 8192,
        }
        headers = {"Content-Type": "application/json"}
        if self.provider == "deepseek":
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider == "anthropic":
            headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"

        http = self._http or httpx.Client(timeout=self.timeout)
        try:
            resp = http.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            usage = data.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            cost = self._compute_cost(input_tokens, output_tokens)
            parsed = self._parse_json_maybe_list(content)
            items = parsed if isinstance(parsed, list) else parsed.get("implementations", [])
            if not isinstance(items, list):
                return []
            results = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item.setdefault("_meta", {}).update(
                    {
                        "model": self.model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost": cost,
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                        "title": title,
                        "url": url,
                    }
                )
                results.append(
                    EnrichmentResult(
                        payload=item,
                        cost=cost,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=self.model,
                    )
                )
            with self._lock:
                self._spent += cost
            return results
        except Exception as exc:
            log.error("LLM multi-enrich failed: %s", exc)
            return []

    def _extract_content(self, data: dict) -> str:
        if self.provider == "anthropic":
            blocks = data.get("content", [])
            return "\n".join(
                b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
            )
        return data["choices"][0]["message"]["content"]

    def _compute_cost(self, input_tokens: int, output_tokens: int) -> float:
        p = self.prices
        return input_tokens * p["input"] + output_tokens * p["output"]

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else parts[0]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        if not isinstance(parsed, dict):
            raise ValueError("LLM response was not a JSON object")
        return parsed

    @staticmethod
    def _parse_json_maybe_list(content: str):
        """Parse a JSON object OR array (multi-extraction returns an array)."""
        text = content.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else parts[0]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    @property
    def spent(self) -> float:
        return self._spent
