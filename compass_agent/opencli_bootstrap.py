"""Best-effort OpenCLI bootstrap for the agent container.

OpenCLI is a Node CLI. The Railway container has no Node, so on first use we
install a standalone Node binary + the OpenCLI npm package into ``/app/tools``
(persisted on the agent volume). The container's ``env`` cannot resolve ``node``
from the opencli shebang, so ``ensure_opencli`` returns an invocation *prefix*
(e.g. ``/app/tools/node/bin/node /app/tools/opencli/bin/opencli``) that the
caller shells out to, and ``opencli_env`` supplies the PATH for child processes.

All steps are guarded: any failure logs a warning and returns '', so Discovery
falls back to DuckDuckGo / curated seeds / Arxiv. No API key is required —
OpenCLI's search adapters are self-contained.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

log = logging.getLogger("compass_agent.opencli")

NODE_VERSION = "v20.19.0"
NODE_URL = f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-linux-x64.tar.xz"
OPENCLI_PACKAGE = "@jackwener/opencli@1.8.3"

TOOLS_DIR = Path(os.environ.get("AGENT_TOOLS_DIR", "/app/tools"))
NODE_BIN = TOOLS_DIR / "node" / "bin" / "node"
NPM_CLI = TOOLS_DIR / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
OPENCLI_BIN = TOOLS_DIR / "opencli" / "bin" / "opencli"


def _download_node() -> bool:
    if NODE_BIN.exists():
        return True
    try:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        archive = TOOLS_DIR / "node.tar.xz"
        log.info("Downloading Node %s (%s)", NODE_VERSION, NODE_URL)
        urllib.request.urlretrieve(NODE_URL, str(archive))
        log.info("Extracting Node…")
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(TOOLS_DIR)
        extracted = TOOLS_DIR / f"node-{NODE_VERSION}-linux-x64"
        if extracted.exists() and not (TOOLS_DIR / "node").exists():
            extracted.rename(TOOLS_DIR / "node")
        archive.unlink(missing_ok=True)
        return NODE_BIN.exists()
    except Exception as exc:
        log.warning("Node download failed: %s", exc)
        return False


def _install_opencli() -> bool:
    if OPENCLI_BIN.exists():
        return True
    if not NODE_BIN.exists() or not NPM_CLI.exists():
        return False
    env = dict(os.environ)
    env["PATH"] = f"{TOOLS_DIR / 'node' / 'bin'}:{env.get('PATH', '')}"
    try:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Installing OpenCLI (%s)", OPENCLI_PACKAGE)
        result = subprocess.run(
            [
                str(NODE_BIN),
                str(NPM_CLI),
                "install",
                "-g",
                "--prefix",
                str(TOOLS_DIR / "opencli"),
                OPENCLI_PACKAGE,
            ],
            capture_output=True,
            text=True,
            timeout=240,
            env=env,
        )
        if result.returncode != 0:
            log.warning("OpenCLI install failed: %s", (result.stderr or result.stdout)[-400:])
            return False
        return OPENCLI_BIN.exists()
    except Exception as exc:
        log.warning("OpenCLI install error: %s", exc)
        return False


def ensure_opencli() -> str:
    """Return an invocation *prefix* for opencli (system or bootstrapped), or ''."""
    system = shutil.which("opencli")
    if system:
        return system
    try:
        if not (_download_node() and _install_opencli()):
            return ""
        return f"{NODE_BIN} {OPENCLI_BIN}"
    except Exception as exc:
        log.warning("opencli bootstrap error: %s", exc)
        return ""


def opencli_env() -> dict:
    """Environment with the bootstrapped node bin on PATH for child processes."""
    env = dict(os.environ)
    if NODE_BIN.exists():
        env["PATH"] = f"{TOOLS_DIR / 'node' / 'bin'}:{env.get('PATH', '')}"
    return env
