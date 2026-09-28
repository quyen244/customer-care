"""Provision Metabase as code: admin user, warehouse connection, questions and dashboards.

Idempotent: an existing dashboard with the same name is left untouched unless MB_FORCE_RECREATE=true.
Stdlib only, so it runs in a plain python:3.12-slim container.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

from dashboards import DASHBOARDS, FILTERS

MB = os.getenv("MB_URL", "http://metabase:3000").rstrip("/")
DB_NAME = "Customer Care Warehouse"
COLLECTION = "Customer Care"
SYNC_SCHEMAS = "marts,data_quality,alerting"
REQUIRED_TABLES = {"fact_tickets", "fact_sla", "fact_csat", "fact_agent_performance", "mart_daily_sla_summary",
                   "dim_date", "dim_agent", "dim_channel", "dim_priority", "dim_ticket_category",
                   "ingestion_runs", "rejected_records", "alert_log"}
session: str | None = None


def log(msg: str) -> None:
    print(f"[metabase-bootstrap] {msg}", flush=True)


def api(method: str, path: str, body=None, ok=(200, 202, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{MB}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if session:
        req.add_header("X-Metabase-Session", session)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from None


def wait_healthy(timeout_s: int = 600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if api("GET", "/api/health").get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError("Metabase did not become healthy")


def login() -> None:
    global session
    props = api("GET", "/api/session/properties")
    email, password = os.environ["MB_ADMIN_EMAIL"], os.environ["MB_ADMIN_PASSWORD"]
    if not props.get("has-user-setup"):
        log("first run: creating admin user")
        res = api("POST", "/api/setup", {
            "token": props["setup-token"],
            "user": {"email": email, "password": password, "first_name": "Customer Care",
                     "last_name": "Admin", "site_name": "Customer Care Analytics"},
            "prefs": {"site_name": "Customer Care Analytics", "site_locale": "en", "allow_tracking": False},
        })
        session = res["id"]
    else:
        session = api("POST", "/api/session", {"username": email, "password": password})["id"]


def ensure_database() -> int:
    for db in api("GET", "/api/database")["data"]:
        if db["name"] == DB_NAME:
            return db["id"]
    log("registering warehouse connection (read-only role bi_reader)")
    db = api("POST", "/api/database", {
        "engine": "postgres",
        "name": DB_NAME,
        "details": {
            "host": os.getenv("WAREHOUSE_HOST", "postgres"), "port": 5432,
            "dbname": os.getenv("WAREHOUSE_DB", "customer_care"),
            "user": os.environ["WAREHOUSE_BI_USER"], "password": os.environ["WAREHOUSE_BI_PASSWORD"],
            "ssl": False, "schema-filters-type": "inclusion", "schema-filters-patterns": SYNC_SCHEMAS,
        },
        "is_full_sync": True,
    })
    return db["id"]


def wait_for_tables(db_id: int, timeout_s: int = 1800) -> dict[tuple[str, str], int]:
    """Marts exist only after the first successful Airflow run, so keep re-syncing until they appear."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        meta = api("GET", f"/api/database/{db_id}/metadata")
        tables = {t["name"]: t for t in meta["tables"]}
        missing = REQUIRED_TABLES - tables.keys()
        if not missing and all(tables[t]["fields"] for t in REQUIRED_TABLES):
            return {(t["name"], f["name"]): f["id"] for t in meta["tables"] for f in t["fields"]}
        log(f"waiting for warehouse tables (missing: {sorted(missing)}); triggering sync")
        api("POST", f"/api/database/{db_id}/sync_schema")
        time.sleep(20)
    raise TimeoutError("warehouse tables never appeared - has the Airflow pipeline run successfully?")


def prepare_filter_fields(fields: dict) -> None:
    for f in FILTERS.values():
        if f["widget"].startswith("string"):
            fid = fields[(f["table"], f["column"])]
            api("PUT", f"/api/field/{fid}", {"has_field_values": "list"})
            api("POST", f"/api/field/{fid}/rescan_values")


def ensure_collection() -> int:
    for c in api("GET", "/api/collection"):
        if c.get("name") == COLLECTION and not c.get("archived"):
            return c["id"]
    return api("POST", "/api/collection", {"name": COLLECTION, "color": "#509EE3",
                                           "description": "Customer Care SLA, CSAT and pipeline health"})["id"]


def template_tags(filter_names: list[str], fields: dict) -> dict:
    tags = {}
    for name in filter_names:
        f = FILTERS[name]
        tags[name] = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-filter-{name}")),
            "name": name, "display-name": f["label"], "type": "dimension",
            "dimension": ["field", fields[(f["table"], f["column"])], None],
            "widget-type": f["widget"],
        }
    return tags


def build_dashboard(spec: dict, db_id: int, coll_id: int, fields: dict) -> int:
    existing = [d for d in api("GET", "/api/dashboard") if d["name"] == spec["name"] and not d.get("archived")]
    force = os.getenv("MB_FORCE_RECREATE", "false").lower() == "true"
    if existing and not force:
        log(f"dashboard '{spec['name']}' already exists (id {existing[0]['id']}), leaving it untouched")
        return existing[0]["id"]
    for d in existing:
        api("PUT", f"/api/dashboard/{d['id']}", {"archived": True})

    params = [{"id": f"p_{n}", "name": FILTERS[n]["label"], "slug": n, "type": FILTERS[n]["widget"],
               "sectionId": "date" if n == "date" else "string",
               **({"default": spec["default_date"]} if n == "date" and spec.get("default_date") else {})}
              for n in spec["filters"]]
    dash = api("POST", "/api/dashboard", {"name": spec["name"], "description": spec["description"],
                                          "collection_id": coll_id, "parameters": params})
    dashcards = []
    for i, card in enumerate(spec["cards"]):
        created = api("POST", "/api/card", {
            "name": card["name"],
            "description": card.get("description"),
            "display": card["display"],
            "collection_id": coll_id,
            "visualization_settings": card.get("viz", {}),
            "dataset_query": {
                "type": "native", "database": db_id,
                "native": {"query": card["sql"].strip(), "template-tags": template_tags(card["filters"], fields)},
            },
        })
        col, row, w, h = card["pos"]
        dashcards.append({
            "id": -(i + 1), "card_id": created["id"], "row": row, "col": col, "size_x": w, "size_y": h,
            "parameter_mappings": [{"parameter_id": f"p_{n}", "card_id": created["id"],
                                    "target": ["dimension", ["template-tag", n]]} for n in card["filters"]],
            "visualization_settings": {},
        })
    api("PUT", f"/api/dashboard/{dash['id']}", {"dashcards": dashcards, "width": "full"})
    log(f"created dashboard '{spec['name']}' (id {dash['id']}) with {len(dashcards)} cards")
    return dash["id"]


def public_link(dash_id: int) -> str:
    """Login-free, read-only link (Metabase OSS cannot disable auth, but public dashboards need none)."""
    uuid_ = api("GET", f"/api/dashboard/{dash_id}").get("public_uuid")
    if not uuid_:
        uuid_ = api("POST", f"/api/dashboard/{dash_id}/public_link")["uuid"]
    return f"{os.getenv('MB_PUBLIC_URL', 'http://localhost:3000')}/public/dashboard/{uuid_}"


def main() -> int:
    wait_healthy()
    login()
    db_id = ensure_database()
    fields = wait_for_tables(db_id)
    prepare_filter_fields(fields)
    coll_id = ensure_collection()
    ids = [build_dashboard(spec, db_id, coll_id, fields) for spec in DASHBOARDS]
    api("PUT", "/api/setting/custom-homepage", {"value": True})
    api("PUT", "/api/setting/custom-homepage-dashboard", {"value": ids[0]})
    api("PUT", "/api/setting/enable-public-sharing", {"value": True})
    for spec, dash_id in zip(DASHBOARDS, ids):
        log(f"no-login link for '{spec['name']}': {public_link(dash_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
