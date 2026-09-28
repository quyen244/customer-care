from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import execute_values

RAW_COLUMNS = {
    "tickets": ["ticket_id", "customer_id", "agent_id", "subject", "category", "subcategory",
                "priority", "channel", "status", "created_at", "first_response_at",
                "resolved_at", "closed_at", "reopened_at", "reopen_count", "updated_at"],
    "agents": ["agent_id", "agent_name", "email", "team", "shift", "hire_date",
               "termination_date", "is_active", "updated_at"],
    "sales_orders": ["order_id", "customer_id", "order_date", "plan", "order_type",
                     "billing_cycle", "amount", "currency", "status", "sales_rep", "updated_at"],
    "csat_surveys": ["survey_id", "ticket_id", "customer_id", "sent_at", "responded_at",
                     "score", "comment", "updated_at"],
    "crm_customers": ["customer_id", "company_name", "contact_name", "email", "phone",
                      "segment", "industry", "region", "country", "plan_tier", "billing_cycle",
                      "account_manager", "signup_date", "is_active", "churn_date", "updated_at"],
}
KEYS = {"tickets": "ticket_id", "agents": "agent_id", "sales_orders": "order_id",
        "csat_surveys": "survey_id", "crm_customers": "customer_id"}


@contextmanager
def connect():
    conn = psycopg2.connect(
        host=os.getenv("WAREHOUSE_HOST", "localhost"),
        port=int(os.getenv("WAREHOUSE_PORT", "5432")),
        dbname=os.getenv("WAREHOUSE_DB", "customer_care"),
        user=os.getenv("WAREHOUSE_USER", "etl_user"),
        password=os.environ["WAREHOUSE_PASSWORD"],
        application_name="cc_ingestion",
        connect_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


def upsert(cur, source: str, rows: list[dict], batch_id: str, origin: str) -> tuple[int, int]:
    """Upsert on the natural key. Returns (inserted, updated).

    An existing row is only overwritten by a delivery that is at least as fresh AND differs in
    content, so replays of the same data are true no-ops (no _loaded_at bump, nothing for
    incremental dbt models to reprocess).
    """
    if not rows:
        return 0, 0
    cols = RAW_COLUMNS[source]
    key = KEYS[source]
    table = f"raw.{source}"
    data_cols = [c for c in cols if c != key]
    sql = f"""
        INSERT INTO {table} ({", ".join(cols)}, _batch_id, _source, _loaded_at)
        VALUES %s
        ON CONFLICT ({key}) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols)},
            _batch_id = EXCLUDED._batch_id, _source = EXCLUDED._source, _loaded_at = now()
        WHERE {table}.updated_at <= EXCLUDED.updated_at
          AND ({", ".join(f"{table}.{c}" for c in data_cols)})
              IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in data_cols)})
        RETURNING (xmax = 0) AS inserted
    """
    values = [tuple(r.get(c) for c in cols) + (batch_id, origin) for r in rows]
    result = execute_values(cur, sql, values, template=f"({', '.join(['%s'] * (len(cols) + 2))}, now())",
                            page_size=1000, fetch=True)
    inserted = sum(1 for (ins,) in result if ins)
    return inserted, len(result) - inserted
