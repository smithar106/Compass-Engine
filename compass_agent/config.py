"""Environment configuration for the Compass Evidence Agent.

Configuration is intentionally dependency-free: the agent reads environment
variables directly and validates them before the worker boots, so a missing
or malformed variable fails loudly instead of surfacing deep inside a cycle.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Variables that must be present (non-empty) for the daemon to boot.
REQUIRED_ENV: tuple[str, ...] = ("COMPASS_API_URL",)

# Provider API keys. Not fatal to boot — the worker stays alive in a degraded
# "connectivity-only" mode and pauses LLM work until a key is configured.
PROVIDER_API_KEY_ENV: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    val = str(raw).strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


@dataclass
class Settings:
    compass_api_url: str = ""
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""
    max_daily_llm_usd: float = 0.50
    max_total_llm_usd: float = 3.75
    llm_concurrency: int = 2
    max_docs_per_cycle: int = 10
    sleep_seconds: float = 900
    auto_publish: bool = False
    state_file: str = ""
    candidate_db: str = ""
    auto_download_db: bool = True
    sync_token: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "tuple[Settings, list[str]]":
        """Build settings from an environment mapping (defaults to os.environ).

        Returns ``(settings, problems)``. ``problems`` collects both parse
        errors (unreadable numbers/bools) and semantic validation failures, so
        the caller can fail loudly before any work begins.
        """
        env = os.environ if env is None else env
        problems: list[str] = []

        def _num(name: str, default: float) -> float:
            raw = env.get(name)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                return float(raw)
            except (TypeError, ValueError):
                problems.append(f"{name} must be a number, got {raw!r}")
                return default

        def _int(name: str, default: int) -> int:
            raw = env.get(name)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                problems.append(f"{name} must be an integer, got {raw!r}")
                return default

        api_url = str(env.get("COMPASS_API_URL") or "").strip()
        settings = cls(
            compass_api_url=api_url,
            llm_provider=str(env.get("LLM_PROVIDER") or "deepseek").strip().lower(),
            deepseek_api_key=str(env.get("DEEPSEEK_API_KEY") or ""),
            anthropic_api_key=str(env.get("ANTHROPIC_API_KEY") or ""),
            max_daily_llm_usd=_num("AGENT_MAX_DAILY_LLM_USD", 0.50),
            max_total_llm_usd=_num("AGENT_MAX_TOTAL_LLM_USD", 3.75),
            llm_concurrency=_int("AGENT_LLM_CONCURRENCY", 2),
            max_docs_per_cycle=_int("AGENT_MAX_DOCS_PER_CYCLE", 10),
            sleep_seconds=_num("AGENT_SLEEP_SECONDS", 900),
            auto_publish=_parse_bool(env.get("AGENT_AUTO_PUBLISH"), False),
            state_file=str(env.get("AGENT_STATE_FILE") or "").strip(),
            candidate_db=str(env.get("AGENT_CANDIDATE_DB") or "").strip(),
            auto_download_db=_parse_bool(env.get("AGENT_AUTO_DOWNLOAD_DB"), True),
            sync_token=str(env.get("AGENT_SYNC_TOKEN") or "").strip(),
            log_level=str(env.get("AGENT_LOG_LEVEL") or "INFO").strip().upper(),
        )
        problems.extend(settings.validate())
        return settings, problems

    def validate(self) -> "list[str]":
        """Return a list of configuration problems. Empty means valid."""
        problems: list[str] = []
        if not self.compass_api_url:
            problems.append("COMPASS_API_URL is required")
        elif not (
            self.compass_api_url.startswith("http://")
            or self.compass_api_url.startswith("https://")
        ):
            problems.append("COMPASS_API_URL must be an http(s) URL")
        if self.max_daily_llm_usd <= 0:
            problems.append("AGENT_MAX_DAILY_LLM_USD must be > 0")
        if self.max_total_llm_usd <= 0:
            problems.append("AGENT_MAX_TOTAL_LLM_USD must be > 0")
        if self.max_daily_llm_usd > self.max_total_llm_usd:
            problems.append(
                "AGENT_MAX_DAILY_LLM_USD cannot exceed AGENT_MAX_TOTAL_LLM_USD"
            )
        if self.llm_concurrency < 1:
            problems.append("AGENT_LLM_CONCURRENCY must be >= 1")
        if self.max_docs_per_cycle < 0:
            problems.append("AGENT_MAX_DOCS_PER_CYCLE must be >= 0")
        if self.sleep_seconds < 0:
            problems.append("AGENT_SLEEP_SECONDS must be >= 0")
        return problems

    @property
    def provider_api_key(self) -> str:
        return getattr(self, f"{self.llm_provider}_api_key", "") or ""

    @property
    def provider_api_key_configured(self) -> bool:
        return bool(self.provider_api_key)

    @property
    def missing_provider_key_env(self) -> "str | None":
        """The env var name that would configure the active provider, if any."""
        return PROVIDER_API_KEY_ENV.get(self.llm_provider)


def load_settings() -> "tuple[Settings, list[str]]":
    """Convenience loader used by the CLI and daemon."""
    return Settings.from_env()
