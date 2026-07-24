#!/usr/bin/env python3
"""Compass recommendation HTTP API — wraps recommend() so the Next.js frontend can call it."""

import sys, os, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_collector.analysis.recommendation import recommend


HOST = os.environ.get("COMPASS_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("COMPASS_API_PORT", "8001"))


class RecommendationHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, {"status": "ok", "service": "compass-recommendation"})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/recommend":
            self._handle_recommend()
        else:
            self._json(404, {"error": "not_found"})

    def _handle_recommend(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception as e:
            self._json(400, {"error": f"invalid_body: {e}"})
            return

        workflow = body.get("workflow", "")
        business_function = body.get("business_function", "")
        industry = body.get("industry", "")
        employee_count = body.get("employee_count")
        desired_outcome = body.get("desired_outcome", "")

        if not workflow or not business_function:
            self._json(400, {"error": "workflow and business_function are required"})
            return

        try:
            result = recommend(
                workflow=workflow,
                business_function=business_function,
                industry=industry,
                employee_count=employee_count,
                desired_outcome=desired_outcome,
            )
            self._json(200, result)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, status: int, data: dict):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[compass-api] {args[0]} {args[1]} {args[2]}\n")


def main():
    server = HTTPServer((HOST, PORT), RecommendationHandler)
    print(f"[compass-api] listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[compass-api] shutting down", flush=True)
        server.server_close()


if __name__ == "__main__":
    main()
