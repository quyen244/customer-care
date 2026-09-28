"""Mock CRM REST API (stdlib only).

GET /api/v1/customers?updated_since=<ISO8601>&page=<n>&page_size=<n>   header X-API-Key
GET /health
Customer state is computed live from the simulator at request time, so the CRM keeps
changing (new signups, plan upgrades, churn) exactly like a real system of record.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from simulator import Simulator, parse_start

API_KEY = os.getenv("CRM_API_KEY", "local-dev-key")
FAILURE_RATE = float(os.getenv("CRM_API_FAILURE_RATE", "0.05"))
MAX_PAGE_SIZE = 500
SIM = Simulator(parse_start(os.getenv("SIM_START_DATE", "2026-04-01")), int(os.getenv("SIM_SEED", "42")))
_cache: dict = {"minute": None, "rows": []}
_lock = threading.Lock()
log = logging.getLogger("mock_crm_api")


def _customers_now() -> list[dict]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with _lock:
        if _cache["minute"] != now:
            _cache["rows"] = sorted(SIM.customers(now), key=lambda c: (c["updated_at"], c["customer_id"]))
            _cache["minute"] = now
        return _cache["rows"]


class Handler(BaseHTTPRequestHandler):
    server_version = "MockCRM/1.0"

    def _send(self, code: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/health":
            return self._send(200, {"status": "ok"})
        if url.path != "/api/v1/customers":
            return self._send(404, {"error": "not_found"})
        if self.headers.get("X-API-Key") != API_KEY:
            return self._send(401, {"error": "invalid_api_key"})
        if random.random() < FAILURE_RATE:
            return self._send(503, {"error": "service_unavailable"}, {"Retry-After": "1"})
        q = parse_qs(url.query)
        try:
            page = max(1, int(q.get("page", ["1"])[0]))
            size = min(MAX_PAGE_SIZE, max(1, int(q.get("page_size", ["200"])[0])))
            since = q.get("updated_since", [None])[0]
            since_dt = datetime.fromisoformat(since.replace(" ", "+")) if since else None
            if since_dt and since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            return self._send(400, {"error": "bad_request", "detail": str(exc)})
        rows = _customers_now()
        if since_dt:
            rows = [r for r in rows if r["updated_at"] > since_dt]
        chunk = rows[(page - 1) * size: page * size]
        data = [{**r, "updated_at": r["updated_at"].isoformat().replace("+00:00", "Z")} for r in chunk]
        self._send(200, {"data": data, "page": page, "page_size": size, "total": len(rows),
                         "has_more": page * size < len(rows)})

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    port = int(os.getenv("PORT", "8000"))
    t0 = time.time()
    _customers_now()
    log.info("warm cache in %.2fs, serving on :%d", time.time() - t0, port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
