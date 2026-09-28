"""Export incremental CSV drops from the simulated source systems into the landing zone.

Ticketing (tickets, agents), billing (sales orders) and survey tool (CSAT) deliver CSV
exports containing rows changed since the previous export, like Zendesk/Stripe incremental
exports. CRM data is not exported here; it is served by mock_crm_api.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from simulator import Simulator, parse_start

log = logging.getLogger("generator")

FILE_SOURCES = {
    "tickets": ["ticket_id", "customer_id", "agent_id", "subject", "category", "subcategory",
                "priority", "channel", "status", "created_at", "first_response_at",
                "resolved_at", "closed_at", "reopened_at", "reopen_count", "updated_at"],
    "agents": ["agent_id", "agent_name", "email", "team", "shift", "hire_date",
               "termination_date", "is_active", "updated_at"],
    "sales_orders": ["order_id", "customer_id", "order_date", "plan", "order_type",
                     "billing_cycle", "amount", "currency", "status", "sales_rep", "updated_at"],
    "csat_surveys": ["survey_id", "ticket_id", "customer_id", "sent_at", "responded_at",
                     "score", "comment", "updated_at"],
}
KEYS = {"tickets": "ticket_id", "agents": "agent_id", "sales_orders": "order_id",
        "csat_surveys": "survey_id"}
# Each source system formats timestamps its own way, as real exports do.
TS_FORMAT = {"tickets": "%Y-%m-%dT%H:%M:%SZ", "agents": "%Y-%m-%dT%H:%M:%SZ",
             "sales_orders": "%Y-%m-%d %H:%M:%S", "csat_surveys": "%Y-%m-%d %H:%M:%S"}


def _fmt(value, source: str):
    if isinstance(value, datetime):
        return value.strftime(TS_FORMAT[source])
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else value


def inject_defects(source: str, rows: list[dict], seed: int) -> tuple[list[dict], Counter]:
    """Inject a small, deterministic rate of the defects real exports contain."""
    out, stats = [], Counter()
    for row in rows:
        r = random.Random(f"{seed}:defect:{source}:{row[KEYS[source]]}:{row['updated_at']}")
        row = dict(row)
        x = r.random()
        if source == "tickets":
            if x < 0.003:
                row["customer_id"] = None; stats["null_customer_id"] += 1
            elif x < 0.006:
                row["status"] = r.choice(["in-progres", "Resolvd", "UNKNOWN", "escalated??"]); stats["invalid_status"] += 1
            elif x < 0.009 and row["resolved_at"]:
                row["resolved_at"] = row["created_at"].replace(year=row["created_at"].year - 1); stats["resolved_before_created"] += 1
            elif x < 0.011:
                row["created_at"] = r.choice(["2026-02-30T25:61:00Z", "N/A", "31/12/2026 10:00"]); stats["unparseable_timestamp"] += 1
            elif x < 0.03:
                row["status"] = row["status"].upper() if r.random() < 0.5 else row["status"].title(); stats["status_casing_only"] += 1
        elif source == "csat_surveys":
            if x < 0.003 and row["score"] is not None:
                row["score"] = r.choice([0, 6, 7, 10]); stats["score_out_of_range"] += 1
            elif x < 0.005:
                row["ticket_id"] = None; stats["null_ticket_id"] += 1
        elif source == "sales_orders":
            if x < 0.002:
                row["customer_id"] = None; stats["null_customer_id"] += 1
            elif x < 0.004:
                row["amount"] = -abs(row["amount"]); stats["negative_amount"] += 1
        out.append(row)
        if r.random() < 0.004:  # exporter double-sends a row (at-least-once delivery)
            out.append(dict(row)); stats["exact_duplicate"] += 1
    return out, stats


def write_csv(path: Path, source: str, rows: list[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FILE_SOURCES[source], extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: _fmt(row.get(k), source) for k in FILE_SOURCES[source]})
    tmp.replace(path)  # atomic: ingestion never sees a half-written file


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--landing-dir", default=os.getenv("LANDING_DIR", "./data/landing"))
    p.add_argument("--start-date", default=os.getenv("SIM_START_DATE", "2026-04-01"))
    p.add_argument("--seed", type=int, default=int(os.getenv("SIM_SEED", "42")))
    p.add_argument("--as-of", help="ISO timestamp (UTC). Default: now.")
    p.add_argument("--full", action="store_true", help="Export everything, ignore previous watermark.")
    p.add_argument("--sources", default=",".join(FILE_SOURCES),
                   help="Comma-separated subset to export, e.g. agents (re-deliver one system).")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    as_of = as_of.replace(microsecond=0)
    landing = Path(args.landing_dir)
    state_file = landing / "_state" / "export_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    if args.full:
        state = {k: v for k, v in state.items() if k not in args.sources.split(",")}

    snap = Simulator(parse_start(args.start_date), args.seed).snapshot(as_of)
    stamp = as_of.strftime("%Y%m%dT%H%M%SZ")
    summary = {}
    selected = [x.strip() for x in args.sources.split(",")]
    unknown = set(selected) - FILE_SOURCES.keys()
    if unknown:
        p.error(f"unknown sources: {sorted(unknown)}")
    for source in selected:
        since = datetime.fromisoformat(state[source]) if source in state else None
        if since and as_of <= since:
            log.warning("as_of %s is not after last export %s for %s; skipping", as_of, since, source)
            continue
        rows = [r for r in snap[source] if since is None or r["updated_at"] > since]
        rows, defects = inject_defects(source, rows, args.seed)
        out_dir = landing / source
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{source}_{stamp}.csv"
        write_csv(path, source, rows)
        state[source] = as_of.isoformat()
        summary[source] = {"rows": len(rows), "file": path.name, "defects": dict(defects)}
        log.info("exported %s rows=%d defects=%s -> %s", source, len(rows), dict(defects), path)
    state_file.write_text(json.dumps(state, indent=2))
    print(json.dumps({"as_of": as_of.isoformat(), "exports": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
