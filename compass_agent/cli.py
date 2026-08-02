"""Command-line interface for the Compass Evidence Agent.

Commands::

    python -m compass_agent --help
    python -m compass_agent status
    python -m compass_agent daemon
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from compass_agent import __version__
from compass_agent.config import Settings, load_settings
from compass_agent.daemon import Daemon, check_engine_health, print_startup_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m compass_agent",
        description="Compass Evidence Agent — keeps the evidence pipeline alive "
        "and budget-controlled on Railway.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("status", help="Show configuration, engine connectivity, and status")
    sub.add_parser("daemon", help="Run the worker loop (Railway start command)")
    return parser


def _print_config_errors(problems: list[str]) -> int:
    print("Compass Evidence Agent", flush=True)
    print("Status: configuration error", flush=True)
    for problem in problems:
        print(f"  - {problem}", flush=True)
    return 1


def cmd_status(settings: Settings, problems: list[str]) -> int:
    if problems:
        return _print_config_errors(problems)
    ok, detail = check_engine_health(settings.compass_api_url)
    print_startup_summary(settings, mode="status", engine_ok=ok, engine_detail=detail)
    return 0


def cmd_daemon(settings: Settings, problems: list[str]) -> int:
    if problems:
        return _print_config_errors(problems)

    if not settings.provider_api_key_configured:
        key_env = settings.missing_provider_key_env or "provider API key"
        print(
            f"WARNING: {key_env} is not set — LLM operations will be paused "
            "until configured. The worker stays alive for connectivity and budget.",
            flush=True,
        )

    daemon = Daemon(settings)
    return daemon.run()


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    settings, problems = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "status":
        return cmd_status(settings, problems)
    if args.command == "daemon":
        return cmd_daemon(settings, problems)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
