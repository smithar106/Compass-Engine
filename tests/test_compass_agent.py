"""Tests for the Compass Evidence Agent.

Run from the repo root with::

    python -m unittest tests.test_compass_agent -v
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from compass_agent.config import Settings
from compass_agent.daemon import BudgetTracker, Daemon, check_engine_health

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_ENV = {
    "COMPASS_API_URL": "http://127.0.0.1:65535",
    "LLM_PROVIDER": "deepseek",
    "DEEPSEEK_API_KEY": "test-key",
    "AGENT_MAX_DAILY_LLM_USD": "0.50",
    "AGENT_MAX_TOTAL_LLM_USD": "3.75",
    "AGENT_LLM_CONCURRENCY": "2",
    "AGENT_MAX_DOCS_PER_CYCLE": "10",
    "AGENT_SLEEP_SECONDS": "0",
    "AGENT_AUTO_PUBLISH": "false",
}


def make_settings(**overrides) -> Settings:
    env = dict(AGENT_ENV)
    env.update(overrides)
    settings, problems = Settings.from_env(env)
    assert not problems, problems
    return settings


def _run_module(*args: str, env: dict | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "compass_agent", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestModuleEntryPoint(unittest.TestCase):
    def test_help_exits_zero(self):
        proc = _run_module("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())

    def test_no_args_prints_help(self):
        proc = _run_module()
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())

    def test_version(self):
        proc = _run_module("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0.1.0", proc.stdout)


class TestCli(unittest.TestCase):
    def test_help_raises_system_exit_zero(self):
        from compass_agent.cli import main

        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_status_with_valid_config(self):
        proc = _run_module("status", env=dict(os.environ, **AGENT_ENV))
        self.assertEqual(proc.returncode, 0)
        out = proc.stdout
        self.assertIn("Compass Evidence Agent", out)
        self.assertIn("Mode: status", out)
        self.assertIn("Provider: deepseek", out)
        self.assertIn("Max daily spend: $0.50", out)
        self.assertIn("Max total spend: $3.75", out)
        self.assertIn("Max docs per cycle: 10", out)
        self.assertIn("Auto publish: false", out)
        self.assertIn("Status:", out)

    def test_status_does_not_leak_secrets(self):
        proc = _run_module("status", env=dict(os.environ, **AGENT_ENV))
        self.assertNotIn("test-key", proc.stdout)
        self.assertNotIn("DEEPSEEK_API_KEY=", proc.stdout)


class TestConfig(unittest.TestCase):
    def test_full_config_loading(self):
        settings, problems = Settings.from_env(AGENT_ENV)
        self.assertEqual(problems, [])
        self.assertEqual(settings.compass_api_url, "http://127.0.0.1:65535")
        self.assertEqual(settings.llm_provider, "deepseek")
        self.assertEqual(settings.max_daily_llm_usd, 0.50)
        self.assertEqual(settings.max_total_llm_usd, 3.75)
        self.assertEqual(settings.llm_concurrency, 2)
        self.assertEqual(settings.max_docs_per_cycle, 10)
        self.assertEqual(settings.sleep_seconds, 0)
        self.assertFalse(settings.auto_publish)
        self.assertTrue(settings.provider_api_key_configured)

    def test_defaults_when_vars_absent(self):
        settings, problems = Settings.from_env({"COMPASS_API_URL": "https://x.example"})
        self.assertEqual(problems, [])
        self.assertEqual(settings.llm_provider, "deepseek")
        self.assertEqual(settings.max_daily_llm_usd, 2.50)
        self.assertEqual(settings.max_total_llm_usd, 10.00)
        self.assertEqual(settings.llm_concurrency, 4)
        self.assertEqual(settings.max_docs_per_cycle, 20)
        self.assertEqual(settings.sleep_seconds, 600)
        self.assertFalse(settings.auto_publish)

    def test_auto_publish_parsing(self):
        settings, _ = Settings.from_env({**AGENT_ENV, "AGENT_AUTO_PUBLISH": "true"})
        self.assertTrue(settings.auto_publish)

    def test_store_db_and_budget_state_are_separate(self):
        env = {
            **AGENT_ENV,
            "AGENT_STATE_FILE": "/vol/agent_state.json",
            "AGENT_STORE_DB": "/vol/agent_store.db",
        }
        settings, problems = Settings.from_env(env)
        self.assertEqual(problems, [])
        self.assertEqual(settings.state_file, "/vol/agent_state.json")
        self.assertEqual(settings.store_db, "/vol/agent_store.db")
        self.assertNotEqual(settings.state_file, settings.store_db)

    def test_missing_required_variable(self):
        settings, problems = Settings.from_env({})
        self.assertIn("COMPASS_API_URL is required", problems)

    def test_invalid_budget_ordering(self):
        env = {**AGENT_ENV, "AGENT_MAX_DAILY_LLM_USD": "5", "AGENT_MAX_TOTAL_LLM_USD": "1"}
        _, problems = Settings.from_env(env)
        self.assertIn(
            "AGENT_MAX_DAILY_LLM_USD cannot exceed AGENT_MAX_TOTAL_LLM_USD", problems
        )

    def test_non_numeric_budget_is_reported(self):
        env = {**AGENT_ENV, "AGENT_MAX_DAILY_LLM_USD": "abc"}
        _, problems = Settings.from_env(env)
        self.assertTrue(any("AGENT_MAX_DAILY_LLM_USD" in p for p in problems))

    def test_daemon_refuses_to_start_without_required_vars(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("COMPASS_API_URL")}
        env.pop("COMPASS_API_URL", None)
        proc = _run_module("daemon", env=env, timeout=15)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("COMPASS_API_URL is required", proc.stdout + proc.stderr)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/").endswith("/health") or self.path == "/health":
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence
        pass


class TestEngineReachability(unittest.TestCase):
    def test_check_engine_health_unreachable(self):
        ok, detail = check_engine_health("http://127.0.0.1:1", timeout=2)
        self.assertFalse(ok)
        self.assertIn("unreachable", detail)

    def test_check_engine_health_reachable(self):
        server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            ok, detail = check_engine_health(f"http://127.0.0.1:{port}", timeout=5)
            self.assertTrue(ok)
            self.assertIn("200", detail)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestBudgetTracker(unittest.TestCase):
    def test_enforces_daily_and_total(self):
        b = BudgetTracker(max_daily=1.0, max_total=5.0)
        self.assertTrue(b.can_work())
        b.spend(0.6)
        self.assertTrue(b.can_work())
        b.spend(0.6)  # daily now 1.2 > 1.0
        self.assertFalse(b.can_work())

    def test_enforces_total(self):
        b = BudgetTracker(max_daily=10.0, max_total=5.0)
        b.spend(5.0)
        self.assertFalse(b.can_work())

    def test_state_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "budget.json")
            b1 = BudgetTracker(max_daily=2.0, max_total=10.0, state_file=state)
            b1.spend(1.5)
            b2 = BudgetTracker(max_daily=2.0, max_total=10.0, state_file=state)
            self.assertAlmostEqual(b2.total_spent, 1.5)
            self.assertTrue(b2.can_work())  # daily 1.5 < 2.0, total 1.5 < 10


class TestBudgetAlerts(unittest.TestCase):
    def test_emits_threshold_alerts_once(self):
        import io
        import logging

        from compass_agent.daemon import BudgetTracker

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        logger = logging.getLogger("alert-test")
        logger.setLevel(logging.WARNING)
        logger.handlers = [handler]

        b = BudgetTracker(max_daily=1.0, max_total=10.0)
        notified = []

        # 0.76 -> 76% daily fires the 75% alert (not 90/100)
        b.spend(0.76)
        alerts = b.check_alerts(logger=logger, notify=notified.append)
        self.assertEqual([(a["kind"], a["threshold"]) for a in alerts], [("daily", 75)])
        self.assertEqual(len(notified), 1)

        # second call: nothing new fires
        self.assertEqual(b.check_alerts(logger=logger, notify=notified.append), [])
        self.assertEqual(len(notified), 1)

        # crossing 90%
        b.spend(0.15)  # 0.91 -> 91%
        alerts = b.check_alerts(logger=logger, notify=notified.append)
        self.assertEqual([(a["kind"], a["threshold"]) for a in alerts], [("daily", 90)])
        self.assertEqual(len(notified), 2)

        # daily cap reached
        b.spend(0.09)  # 1.00 -> 100%
        alerts = b.check_alerts(logger=logger, notify=notified.append)
        self.assertEqual([(a["kind"], a["threshold"]) for a in alerts], [("daily", 100)])

        payload = buf.getvalue()
        self.assertIn('"event":"budget_alert"', payload.replace(" ", ""))
        self.assertIn('"threshold":100', payload.replace(" ", ""))

    def test_total_alerts_fire_too(self):
        from compass_agent.daemon import BudgetTracker

        b = BudgetTracker(max_daily=10.0, max_total=4.0)
        b.spend(3.1)  # total 77.5%
        alerts = b.check_alerts(notify=None)
        self.assertIn(("total", 75), [(a["kind"], a["threshold"]) for a in alerts])

    def test_daily_alerts_rearm_on_rollover(self):
        from compass_agent.daemon import BudgetTracker
        from datetime import date, timedelta

        b = BudgetTracker(max_daily=1.0, max_total=10.0, today=date(2026, 8, 2))
        b.spend(0.76)
        b.check_alerts(notify=None)
        self.assertEqual([(k, t) for (k, t) in b._fired], [("daily", 75)])

        # simulate new day
        b2 = BudgetTracker(max_daily=1.0, max_total=10.0, today=date(2026, 8, 3))
        b2._day = date(2026, 8, 3)
        b2.spend(0.76)  # rolls the day, clears daily fired
        alerts = b2.check_alerts(notify=None)
        self.assertIn(("daily", 75), [(a["kind"], a["threshold"]) for a in alerts])


class TestMetrics(unittest.TestCase):
    def test_metrics_report(self):
        import sqlite3

        from compass_agent.metrics import compute_metrics

        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "agent_store.db")
            conn = sqlite3.connect(store)
            conn.executescript(
                """
                CREATE TABLE enrichment_results (
                    id TEXT PRIMARY KEY, candidate_id TEXT, record_id TEXT,
                    payload TEXT, validation TEXT, valid INTEGER,
                    cost REAL, input_tokens INTEGER, output_tokens INTEGER,
                    model TEXT, created_at TEXT
                );
                CREATE TABLE claims (
                    candidate_id TEXT PRIMARY KEY, claimed_at TEXT, status TEXT,
                    owner TEXT, attempts INTEGER, record_id TEXT,
                    doc_id TEXT, source TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO enrichment_results VALUES "
                "('1','c1','r1','{}','{}',1,0.002,100,50,'m','t'),"
                "('2','c2','r2','{}','{}',1,0.001,80,40,'m','t'),"
                "('3','c3','r3','{}','{}',0,0.001,90,45,'m','t')"
            )
            conn.commit()
            conn.close()

            report = compute_metrics(store_db=store, collector_db="")
            self.assertEqual(report["attempted_records"], 3)
            self.assertEqual(report["valid_enrichments"], 2)
            self.assertEqual(report["invalid_enrichments"], 1)
            self.assertAlmostEqual(report["total_cost_usd"], 0.004)
            self.assertEqual(report["cost_per_valid_enrichment"], 0.002)


class TestDaemonBehavior(unittest.TestCase):
    def _captured_logger(self):
        logger = logging.getLogger("compass_agent.test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger, buf

    def test_daemon_startup_runs_bounded_cycles(self):
        settings = make_settings()
        calls = {"n": 0}

        def healthy(url, timeout=10.0):
            calls["n"] += 1
            return True, "200 OK"

        daemon = Daemon(settings, health_check=healthy, sleep_fn=lambda s: None)
        rc = daemon.run(max_cycles=2)
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(calls["n"], 2)

    def test_daemon_retries_engine_then_succeeds(self):
        settings = make_settings()
        calls = {"n": 0}

        def flaky(url, timeout=10.0):
            calls["n"] += 1
            if calls["n"] <= 3:
                return False, "boom"
            return True, "200 OK"

        logger, buf = self._captured_logger()
        daemon = Daemon(
            settings,
            health_check=flaky,
            sleep_fn=lambda s: None,
            initial_backoff=0.01,
            max_backoff=0.05,
            logger=logger,
        )
        rc = daemon.run(max_cycles=3)
        self.assertEqual(rc, 0)
        # startup check (fail) + cycle 1 (fail) + cycle 2+ (success)
        self.assertGreaterEqual(calls["n"], 3)
        self.assertIn("backing off", buf.getvalue())

    def test_daemon_engine_down_does_not_crash(self):
        settings = make_settings()
        calls = {"n": 0}

        def down(url, timeout=10.0):
            calls["n"] += 1
            return False, "boom"

        daemon = Daemon(
            settings,
            health_check=down,
            sleep_fn=lambda s: None,
            initial_backoff=0.01,
            max_backoff=0.05,
        )
        rc = daemon.run(max_cycles=1)
        self.assertEqual(rc, 0)  # stays alive, never crashes
        self.assertGreaterEqual(calls["n"], 2)

    def test_shutdown_flag_stops_loop(self):
        settings = make_settings()
        daemon = Daemon(
            settings,
            health_check=lambda url, timeout=10.0: (True, "ok"),
            sleep_fn=lambda s: None,
        )
        daemon._handle_signal(15, None)  # simulate SIGTERM
        self.assertFalse(daemon._running)

    def test_sleep_interruptible_returns_when_stopped(self):
        settings = make_settings()
        slept = []
        daemon = Daemon(
            settings,
            health_check=lambda url, timeout=10.0: (True, "ok"),
            sleep_fn=slept.append,
        )
        daemon._running = False
        daemon._sleep_interruptible(10)
        self.assertEqual(slept, [])  # does not sleep once stopped


class TestGracefulShutdownSubprocess(unittest.TestCase):
    def test_sigterm_clean_shutdown(self):
        server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            env = dict(os.environ)
            env.update(
                {
                    **AGENT_ENV,
                    "COMPASS_API_URL": f"http://127.0.0.1:{port}",
                    "AGENT_SLEEP_SECONDS": "3600",  # long sleep; must be interrupted
                    "AGENT_AUTO_DOWNLOAD_DB": "0",  # never download the 131MB DB in tests
                }
            )
            proc = subprocess.Popen(
                [sys.executable, "-m", "compass_agent", "daemon"],
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.time() + 30
                output = ""
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if line:
                        output += line
                        if "Status: ready" in output:
                            break
                    elif proc.poll() is not None:
                        break
                self.assertIn("Status: ready", output, msg=output)

                proc.terminate()  # SIGTERM
                rc = proc.wait(timeout=15)
                tail = proc.stdout.read() if proc.stdout else ""
                output += tail
                self.assertEqual(rc, 0, msg=output)
                self.assertIn("shutting down", output.lower())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                if proc.stdout:
                    proc.stdout.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
