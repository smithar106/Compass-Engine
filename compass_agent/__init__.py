"""Compass Evidence Agent.

A lightweight worker that keeps the evidence pipeline alive on Railway,
validates configuration, verifies Engine connectivity, enforces LLM budget
limits, and (in later milestones) runs enrichment, claiming, persistence,
validation, and benchmarking workflows.

Run with::

    python -m compass_agent --help
    python -m compass_agent status
    python -m compass_agent daemon
"""

from __future__ import annotations

__version__ = "0.1.0"

from compass_agent.config import Settings

__all__ = ["Settings", "__version__"]
