"""Tests for collector-DB bootstrap (ensure_collector_db)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from compass_agent.db import ensure_collector_db, is_sqlite_db


def make_db(path: str) -> str:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE intervention_records (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO intervention_records VALUES ('r1')")
    conn.commit()
    conn.close()
    return path


class _DbHandler(BaseHTTPRequestHandler):
    db_path = ""

    def do_GET(self):
        with open(self.db_path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestIsSqliteDb(unittest.TestCase):
    def test_rejects_pointer_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pointer = os.path.join(tmp, "pointer.db")
            with open(pointer, "w") as fh:
                fh.write("version https://git-lfs.github.com/spec/v1\n")
            self.assertFalse(is_sqlite_db(pointer))          # tiny pointer file
            self.assertFalse(is_sqlite_db(os.path.join(tmp, "nope.db")))

    def test_accepts_real_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_db(os.path.join(tmp, "real.db"))
            self.assertTrue(is_sqlite_db(path, min_size=0))


class TestEnsureCollectorDb(unittest.TestCase):
    def test_returns_existing_valid_db_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_db(os.path.join(tmp, "collector.db"))
            got = ensure_collector_db(path=path, urls=["http://127.0.0.1:1/x"], allow_download=True, min_size=0)
            self.assertEqual(got, path)

    def test_downloads_when_pointer_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "data", "collector_v3.db")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w") as fh:  # simulate git-lfs pointer
                fh.write("version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")

            server = HTTPServer(("127.0.0.1", 0), _DbHandler)
            _DbHandler.db_path = make_db(os.path.join(tmp, "src.db"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}/collector_v3.db"
                got = ensure_collector_db(path=target, urls=[url], allow_download=True, min_size=0)
                self.assertEqual(got, target)
                self.assertTrue(is_sqlite_db(target, min_size=0))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_no_download_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "collector.db")
            got = ensure_collector_db(
                path=target,
                urls=["http://127.0.0.1:1/x"],
                allow_download=False,
            )
            self.assertEqual(got, "")
            self.assertFalse(os.path.exists(target))

    def test_download_failure_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "collector.db")
            got = ensure_collector_db(
                path=target,
                urls=["http://127.0.0.1:1/nonexistent"],
                allow_download=True,
            )
            self.assertEqual(got, "")


if __name__ == "__main__":
    unittest.main()
