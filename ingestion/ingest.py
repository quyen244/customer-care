"""Ingest source-system deliveries into the raw layer.

File sources (tickets, agents, sales_orders, csat_surveys): every new CSV in the landing zone
is validated and loaded in ONE transaction together with its quarantine rows and its manifest
entry, then archived. A file is either fully loaded and recorded, or not at all.

API source (crm_customers): paginated pull with an updated_since watermark (minus an overlap
window), retried with exponential backoff on 429/5xx/network errors.

Usage: python -m ingestion.ingest --source all|tickets|agents|sales_orders|csat_surveys|crm_customers
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg2.extras import Json, execute_values

from ingestion.db import connect, upsert
from ingestion.validations import Reject, dedupe, validate_row

FILE_SOURCES = ("agents", "tickets", "sales_orders", "csat_surveys")
API_SOURCES = ("crm_customers",)
WATERMARK_OVERLAP = timedelta(minutes=5)
log = logging.getLogger("ingestion")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        payload.update(getattr(record, "ctx", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def _log(msg: str, **ctx) -> None:
    log.info(msg, extra={"ctx": ctx})


# ------------------------------------------------------------------ run bookkeeping
def _start_run(conn, batch_id: str, source: str, source_file: str | None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO data_quality.ingestion_runs (batch_id, source, source_file, started_at, status)"
            " VALUES (%s, %s, %s, now(), 'running') RETURNING run_id",
            (batch_id, source, source_file))
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _finish_run(conn, run_id: int, status: str, stats: dict, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_quality.ingestion_runs SET finished_at = now(), status = %s, rows_read = %s,"
            " rows_loaded = %s, rows_rejected = %s, rows_duplicate = %s, error = %s WHERE run_id = %s",
            (status, stats.get("read", 0), stats.get("loaded", 0), stats.get("rejected", 0),
             stats.get("duplicates", 0), error, run_id))
    conn.commit()


def _validate(source: str, raw_rows: list[dict]):
    now = datetime.now(timezone.utc)
    typed, rejects = [], []
    for raw in raw_rows:
        try:
            typed.append((raw, validate_row(source, raw, now)))
        except Reject as r:
            rejects.append((raw, r.reason, r.detail))
    kept, dup_rejects = dedupe(source, typed)
    return [t for _, t in kept], rejects + dup_rejects


def _write_rejects(cur, batch_id, source, source_file, key, rejects) -> None:
    if rejects:
        execute_values(cur,
            "INSERT INTO data_quality.rejected_records (batch_id, source, source_file, record_key, reason, detail, raw_record) VALUES %s",
            [(batch_id, source, source_file, (raw.get(key) or None), reason, detail, Json(raw))
             for raw, reason, detail in rejects])


def _summarize(rejects) -> dict:
    out: dict[str, int] = {}
    for _, reason, _ in rejects:
        out[reason] = out.get(reason, 0) + 1
    return out


# ------------------------------------------------------------------ file sources
def ingest_file_source(source: str, landing_dir: Path) -> dict:
    from ingestion.validations import CONTRACTS
    src_dir = landing_dir / source
    files = sorted(src_dir.glob(f"{source}_*.csv")) if src_dir.exists() else []
    totals = {"source": source, "files": 0, "read": 0, "inserted": 0, "updated": 0,
              "unchanged": 0, "rejected": 0, "duplicates": 0}
    if not files:
        _log("no new files", source=source)
        return totals
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_name FROM data_quality.ingested_files WHERE source = %s", (source,))
            done = {r[0] for r in cur.fetchall()}
        conn.commit()
        for path in files:
            if path.name in done:
                _archive(path)  # loaded earlier but archiving failed afterwards
                continue
            batch_id = str(uuid.uuid4())
            run_id = _start_run(conn, batch_id, source, path.name)
            stats = {"read": 0}
            try:
                with path.open(newline="", encoding="utf-8") as fh:
                    raw_rows = list(csv.DictReader(fh))
                stats["read"] = len(raw_rows)
                valid, rejects = _validate(source, raw_rows)
                with conn.cursor() as cur:
                    inserted, updated = upsert(cur, source, valid, batch_id, f"file:{path.name}")
                    _write_rejects(cur, batch_id, source, path.name, CONTRACTS[source].key, rejects)
                    cur.execute(
                        "INSERT INTO data_quality.ingested_files (source, file_name, sha256, batch_id) VALUES (%s, %s, %s, %s)",
                        (source, path.name, hashlib.sha256(path.read_bytes()).hexdigest(), batch_id))
                conn.commit()
                dup = sum(1 for _, reason, _ in rejects if reason in ("duplicate_record", "conflicting_duplicate"))
                stats.update(loaded=inserted + updated, rejected=len(rejects) - dup, duplicates=dup)
                _finish_run(conn, run_id, "success", stats)
                _log("file ingested", source=source, file=path.name, batch_id=batch_id,
                     read=stats["read"], inserted=inserted, updated=updated,
                     unchanged=len(valid) - inserted - updated, rejected=stats["rejected"],
                     duplicates=dup, reject_reasons=_summarize(rejects))
                totals["files"] += 1
                for k, v in (("read", stats["read"]), ("inserted", inserted), ("updated", updated),
                             ("unchanged", len(valid) - inserted - updated),
                             ("rejected", stats["rejected"]), ("duplicates", dup)):
                    totals[k] += v
                _archive(path)
            except Exception as exc:
                conn.rollback()
                _finish_run(conn, run_id, "failed", stats, error=repr(exc)[:2000])
                log.exception("file ingestion failed", extra={"ctx": {"source": source, "file": path.name}})
                raise
    return totals


def _archive(path: Path) -> None:
    dest = path.parent / "archive" / path.name[len(path.parent.name) + 1:][:8]
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest / path.name)


# ------------------------------------------------------------------ API source
def _http_get_json(url: str, api_key: str, max_attempts: int = 5) -> dict:
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(url, headers={"X-API-Key": api_key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == max_attempts:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) or 2 ** (attempt - 1)
            _log("retrying API call", url=url, status=exc.code, attempt=attempt, wait_s=wait)
        except urllib.error.URLError as exc:
            if attempt == max_attempts:
                raise
            wait = 2 ** (attempt - 1)
            _log("retrying API call", url=url, error=str(exc.reason), attempt=attempt, wait_s=wait)
        time.sleep(wait)
    raise RuntimeError("unreachable")


def ingest_crm_api(base_url: str, api_key: str, page_size: int = 500) -> dict:
    source = "crm_customers"
    batch_id = str(uuid.uuid4())
    stats = {"source": source, "read": 0, "inserted": 0, "updated": 0, "unchanged": 0,
             "rejected": 0, "duplicates": 0}
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT watermark FROM data_quality.source_watermarks WHERE source = %s", (source,))
            row = cur.fetchone()
        conn.commit()
        since = (row[0] - WATERMARK_OVERLAP) if row else None
        run_id = _start_run(conn, batch_id, source, f"api:updated_since={since.isoformat() if since else 'full'}")
        try:
            raw_rows, page = [], 1
            while True:
                params = {"page": page, "page_size": page_size}
                if since:
                    params["updated_since"] = since.isoformat()
                body = _http_get_json(f"{base_url}/api/v1/customers?{urllib.parse.urlencode(params)}", api_key)
                raw_rows.extend(body["data"])
                if not body["has_more"]:
                    break
                page += 1
            stats["read"] = len(raw_rows)
            valid, rejects = _validate(source, raw_rows)
            with conn.cursor() as cur:
                inserted, updated = upsert(cur, source, valid, batch_id, "api:crm")
                _write_rejects(cur, batch_id, source, None, "customer_id", rejects)
                if valid:
                    cur.execute(
                        "INSERT INTO data_quality.source_watermarks (source, watermark) VALUES (%s, %s)"
                        " ON CONFLICT (source) DO UPDATE SET watermark = GREATEST(source_watermarks.watermark, EXCLUDED.watermark), updated_at = now()",
                        (source, max(r["updated_at"] for r in valid)))
            conn.commit()
            dup = sum(1 for _, reason, _ in rejects if reason in ("duplicate_record", "conflicting_duplicate"))
            stats.update(inserted=inserted, updated=updated, unchanged=len(valid) - inserted - updated,
                         rejected=len(rejects) - dup, duplicates=dup, loaded=inserted + updated, pages=page)
            _finish_run(conn, run_id, "success", stats)
            _log("api ingested", batch_id=batch_id, since=since, reject_reasons=_summarize(rejects), **stats)
        except Exception as exc:
            conn.rollback()
            _finish_run(conn, run_id, "failed", stats, error=repr(exc)[:2000])
            log.exception("api ingestion failed", extra={"ctx": {"source": source}})
            raise
    return stats


def run(source: str) -> dict | list[dict]:
    landing = Path(os.getenv("LANDING_DIR", "/data/landing"))
    if source == "crm_customers":
        return ingest_crm_api(os.getenv("CRM_API_URL", "http://crm-api:8000"),
                              os.getenv("CRM_API_KEY", "local-dev-key"))
    if source in FILE_SOURCES:
        return ingest_file_source(source, landing)
    if source == "all":
        return [run(s) for s in (*API_SOURCES, *FILE_SOURCES)]
    raise ValueError(f"unknown source {source}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ingest source deliveries into raw.*")
    p.add_argument("--source", default="all", choices=["all", *API_SOURCES, *FILE_SOURCES])
    args = p.parse_args(argv)
    setup_logging()
    print(json.dumps(run(args.source), default=str, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
