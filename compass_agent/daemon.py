"""Daemon loop for the Compass Evidence Agent.

Responsibilities for the minimum deployable milestone:
  * load and validate configuration (via the CLI);
  * verify the Engine is reachable, backing off and retrying if not;
  * enforce daily and total LLM budget limits;
  * run a bounded sleep/work loop that stays alive on Railway;
  * shut down cleanly on SIGTERM/SIGINT.

The enrichment/claiming/persistence logic is intentionally a stub at this
milestone. The loop, budget gate, and connectivity handling are fully wired so
work can be dropped into ``_do_work_cycle`` without reworking the scaffolding.
"""

from __future__ import annotations

import json
import logging
import signal
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from compass_agent.config import Settings

log = logging.getLogger("compass_agent")

# Defaults for the connectivity back-off. Exposed as constructor args so tests
# can drive them down to near-zero and stay fast.
DEFAULT_INITIAL_BACKOFF_SECONDS = 5.0
DEFAULT_MAX_BACKOFF_SECONDS = 60.0


def check_engine_health(url: str, timeout: float = 10.0) -> "tuple[bool, str]":
    """Return ``(reachable, detail)`` for the Engine ``/health`` endpoint.

    Uses only the standard library so the agent boots with zero runtime
    dependencies beyond the configured API key.
    """
    endpoint = f"{url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, f"GET {endpoint} -> 200 OK"
            return False, f"GET {endpoint} -> HTTP {resp.status}"
    except Exception as exc:  # network errors, timeouts, DNS, etc.
        return False, f"GET {endpoint} -> unreachable ({type(exc).__name__}: {exc})"


def print_startup_summary(
    settings: Settings,
    mode: str,
    engine_ok: bool,
    engine_detail: str = "",
    status: str = "",
) -> None:
    """Print the startup block to stdout. Never prints secrets (keys, tokens)."""
    connection = "verified" if engine_ok else f"unreachable ({engine_detail})"
    if not status:
        status = "ready" if engine_ok else "engine unreachable — retrying"
    lines = [
        "Compass Evidence Agent",
        f"Mode: {mode}",
        f"Provider: {settings.llm_provider}",
        f"Engine connection: {connection}",
        f"Max daily spend: ${settings.max_daily_llm_usd:.2f}",
        f"Max total spend: ${settings.max_total_llm_usd:.2f}",
        f"Max docs per cycle: {settings.max_docs_per_cycle}",
        f"Sleep interval: {settings.sleep_seconds:g} seconds",
        f"Auto publish: {'true' if settings.auto_publish else 'false'}",
        f"Status: {status}",
    ]
    print("\n".join(lines), flush=True)


class BudgetTracker:
    """Tracks LLM spend against daily and total budget ceilings.

    State is persisted to ``state_file`` when provided (optional — Railway
    volumes are *not* required). Without a state file, spend is in-memory and
    resets on restart, which is acceptable for the minimum milestone.
    """

    def __init__(
        self,
        max_daily: float,
        max_total: float,
        state_file: str = "",
        today: Optional[date] = None,
    ) -> None:
        self.max_daily = max_daily
        self.max_total = max_total
        self.state_file = state_file
        self._day = today or date.today()
        self._daily_spent = 0.0
        self._total_spent = 0.0
        self._load()

    # -- persistence -------------------------------------------------------
    def _state_path(self) -> Optional[Path]:
        return Path(self.state_file) if self.state_file else None

    def _load(self) -> None:
        path = self._state_path()
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._total_spent = float(data.get("total_spent", 0.0))
            saved_day = data.get("day")
            if saved_day == self._day.isoformat():
                self._daily_spent = float(data.get("daily_spent", 0.0))
            else:
                self._daily_spent = 0.0
        except Exception as exc:
            log.warning("Could not load budget state from %s: %s", path, exc)

    def _save(self) -> None:
        path = self._state_path()
        if not path:
            return
        try:
            path.write_text(
                json.dumps(
                    {
                        "day": self._day.isoformat(),
                        "daily_spent": round(self._daily_spent, 6),
                        "total_spent": round(self._total_spent, 6),
                    }
                )
            )
        except Exception as exc:
            log.warning("Could not persist budget state to %s: %s", path, exc)

    # -- spend -------------------------------------------------------------
    def spend(self, amount: float) -> None:
        if amount < 0:
            raise ValueError("spend amount cannot be negative")
        now = date.today()
        if now != self._day:
            self._day = now
            self._daily_spent = 0.0
        self._daily_spent += amount
        self._total_spent += amount
        self._save()

    def can_work(self) -> bool:
        return (
            self._total_spent < self.max_total
            and self._daily_spent < self.max_daily
        )

    @property
    def daily_spent(self) -> float:
        return self._daily_spent

    @property
    def total_spent(self) -> float:
        return self._total_spent


class Daemon:
    """Bounded sleep/work loop with connectivity retry and budget gating."""

    def __init__(
        self,
        settings: Settings,
        *,
        health_check: Callable[..., tuple[bool, str]] = check_engine_health,
        sleep_fn: Optional[Callable[[float], None]] = None,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff: float = DEFAULT_MAX_BACKOFF_SECONDS,
        logger: Optional[logging.Logger] = None,
        enrichment=None,
        budget: Optional[BudgetTracker] = None,
    ) -> None:
        self.settings = settings
        self.health_check = health_check
        self._sleep = sleep_fn or time.sleep
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.logger = logger or log
        self.enrichment = enrichment
        self.budget = budget or BudgetTracker(
            max_daily=settings.max_daily_llm_usd,
            max_total=settings.max_total_llm_usd,
            state_file=settings.state_file,
        )
        self._running = False
        self._shutdown_requested = False

    # -- signals -----------------------------------------------------------
    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._handle_signal)
            except ValueError:
                # Only the main thread can install signal handlers.
                pass

    def _handle_signal(self, signum, frame) -> None:
        self.logger.info("Received signal %s — shutting down gracefully.", signum)
        self._shutdown_requested = True
        self._running = False

    # -- startup -----------------------------------------------------------
    def _verify_engine(self) -> "tuple[bool, str]":
        return self.health_check(self.settings.compass_api_url)

    # -- sleep -------------------------------------------------------------
    def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small slices so a signal wakes us promptly."""
        remaining = float(seconds)
        while remaining > 0 and self._running:
            chunk = min(1.0, remaining)
            self._sleep(chunk)
            remaining -= chunk

    # -- work --------------------------------------------------------------
    def _do_work_cycle(self, cycle: int) -> int:
        """One unit of work. Budget-gated; returns documents processed."""
        if not self.budget.can_work():
            self.logger.warning(
                "Budget exhausted — daily spent $%.2f / %.2f, total $%.2f / %.2f. "
                "Skipping work this cycle.",
                self.budget.daily_spent,
                self.settings.max_daily_llm_usd,
                self.budget.total_spent,
                self.settings.max_total_llm_usd,
            )
            return 0

        if self.enrichment is not None:
            report = self.enrichment.run_cycle(
                cycle=cycle,
                max_docs=self.settings.max_docs_per_cycle,
            )
            self.logger.info(
                "Cycle %d: enrichment candidates=%d valid=%d invalid=%d skipped=%d "
                "published=%d cost=$%.4f (daily $%.2f / %.2f, total $%.2f / %.2f).",
                cycle,
                report.candidates,
                report.valid,
                report.invalid,
                report.skipped,
                report.published,
                report.cost,
                self.budget.daily_spent,
                self.settings.max_daily_llm_usd,
                self.budget.total_spent,
                self.settings.max_total_llm_usd,
            )
            for failure in report.failures[:5]:
                self.logger.warning("Cycle %d: %s", cycle, failure)
            return report.processed

        self.logger.info(
            "Cycle %d: budget OK (daily $%.2f / %.2f, total $%.2f / %.2f). "
            "No enrichment pipeline configured — idle.",
            cycle,
            self.budget.daily_spent,
            self.settings.max_daily_llm_usd,
            self.budget.total_spent,
            self.settings.max_total_llm_usd,
        )
        return 0

    # -- main loop ---------------------------------------------------------
    def run(self, max_cycles: Optional[int] = None) -> int:
        self._install_signal_handlers()
        self._running = True
        self.logger.info("Starting Compass Evidence Agent daemon.")

        # Single connectivity check at startup. Retries/backoff are owned by the
        # main cycle loop below, so the worker is always responsive to signals
        # even when the Engine is down.
        ok, detail = self._verify_engine()
        print_startup_summary(self.settings, mode="daemon", engine_ok=ok, engine_detail=detail)
        if ok:
            self.logger.info("Engine connection: verified (%s).", detail)
        else:
            self.logger.error("Engine unreachable at startup: %s — will retry with backoff.", detail)

        cycle = 0
        backoff = self.initial_backoff
        while self._running:
            if max_cycles is not None and cycle >= max_cycles:
                break
            cycle += 1

            ok, detail = self._verify_engine()
            if ok:
                backoff = self.initial_backoff
                self._do_work_cycle(cycle)
            else:
                self.logger.error(
                    "Engine unreachable: %s — backing off %.1fs.", detail, backoff
                )
                self._sleep_interruptible(backoff)
                backoff = min(backoff * 2, self.max_backoff)
                continue

            if self._running:
                self._sleep_interruptible(self.settings.sleep_seconds)

        self._running = False
        self.logger.info("Compass Evidence Agent stopped.")
        return 0


def run_daemon(settings: Settings, max_cycles: Optional[int] = None) -> int:
    return Daemon(settings).run(max_cycles=max_cycles)
