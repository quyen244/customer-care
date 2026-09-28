"""Customer Care data pipeline: ingest -> data-quality gate -> dbt (staging, marts) -> n8n alert check."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import TaskGroup, dag, task

log = logging.getLogger(__name__)

SOURCES = ["crm_customers", "agents", "tickets", "sales_orders", "csat_surveys"]
MAX_REJECT_RATE = float(os.getenv("MAX_REJECT_RATE", "0.05"))
MIN_ROWS_FOR_RATE = int(os.getenv("MIN_ROWS_FOR_RATE", "100"))
SMALL_BATCH_MIN_REJECTS = 5
SMALL_BATCH_MAX_RATE = 0.5
N8N_WEBHOOK_BASE = os.getenv("N8N_WEBHOOK_BASE", "http://n8n:5678/webhook")
DBT = (
    "cd $DBT_PROJECT_DIR && $DBT_BIN --no-use-colors {cmd} "
    "--target-path $DBT_TARGET_PATH --log-path $DBT_LOG_PATH"
)


def _post_json(url: str, payload: dict, timeout: int = 30) -> str:
    req = urllib.request.Request(url, data=json.dumps(payload, default=str).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def _dbt_failures() -> str:
    """Names of failed dbt nodes from the last invocation, so the alert says WHAT broke."""
    path = os.path.join(os.getenv("DBT_TARGET_PATH", "/tmp/dbt/target"), "run_results.json")
    try:
        with open(path) as fh:
            results = json.load(fh)["results"]
    except (OSError, ValueError, KeyError):
        return ""
    failed = [f"{r['unique_id']} ({r['status']}: {(r.get('message') or '').strip()[:150]})"
              for r in results if r.get("status") in ("fail", "error")]
    return "; ".join(failed)


def notify_failure(context) -> None:
    ti = context["ti"]
    error = str(context.get("exception"))
    if ti.task_id.startswith("dbt_"):
        error = _dbt_failures() or error
    payload = {
        "event": "pipeline_task_failed",
        "dag_id": ti.dag_id,
        "task_id": ti.task_id,
        "run_id": context.get("run_id"),
        "try_number": ti.try_number,
        "error": error[:1500],
    }
    try:
        _post_json(f"{N8N_WEBHOOK_BASE}/cc-pipeline-failure", payload, timeout=10)
    except Exception:  # alerting must never mask the original failure
        log.exception("could not notify n8n about failure")


default_args = {
    "owner": "customer-care-data",
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=20),
    "on_failure_callback": notify_failure,
}


@dag(
    dag_id="customer_care_pipeline",
    description="Ingest CRM/ticketing/billing/CSAT sources, build SLA marts, trigger alert checks",
    schedule="5 * * * *",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["customer-care", "sla", "dbt"],
    doc_md=__doc__,
)
def customer_care_pipeline():
    with TaskGroup("ingest", tooltip="Validate + upsert each source into raw.*") as ingest:
        results = []
        for source in SOURCES:
            @task(task_id=f"ingest_{source}")
            def ingest_source(src: str) -> dict:
                from ingestion.ingest import run, setup_logging
                setup_logging()
                return run(src)

            results.append(ingest_source(source))

    @task(retries=0)
    def data_quality_gate(stats: list[dict]) -> dict:
        """Fail fast when rejects look systemic (schema change, broken export), not on random bad rows."""
        # A rate needs a real sample: 1 bad row in a 9-row batch is 11% but harmless.
        summary, breaches = {}, []
        for s in stats:
            read, rejected = s.get("read", 0), s.get("rejected", 0)
            rate = (rejected / read) if read else 0.0
            summary[s["source"]] = {**s, "reject_rate": round(rate, 4)}
            log.info("dq %s read=%s rejected=%s duplicates=%s reject_rate=%.2f%%",
                     s["source"], read, rejected, s.get("duplicates", 0), rate * 100)
            if read >= MIN_ROWS_FOR_RATE and rate > MAX_REJECT_RATE:
                breaches.append(f"{s['source']}: {rate:.1%} of {read} rows rejected (limit {MAX_REJECT_RATE:.0%})")
            elif read < MIN_ROWS_FOR_RATE and rejected >= SMALL_BATCH_MIN_REJECTS and rate > SMALL_BATCH_MAX_RATE:
                breaches.append(f"{s['source']}: {rejected} of {read} rows rejected in a small batch")
        if breaches:
            raise ValueError("Data quality gate failed: " + "; ".join(breaches))
        return summary

    source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        bash_command=DBT.format(cmd="source freshness"),
        retries=0,
    )
    seed = BashOperator(task_id="dbt_seed", bash_command=DBT.format(cmd="seed"))
    run_staging = BashOperator(task_id="dbt_run_staging", bash_command=DBT.format(cmd="run --select staging"))
    test_staging = BashOperator(
        task_id="dbt_test_staging",
        bash_command=DBT.format(cmd="test --select staging source:raw seed_sla_policy"),
        retries=0,  # a failing data test is deterministic; retrying only delays the alert
    )
    run_marts = BashOperator(task_id="dbt_run_marts", bash_command=DBT.format(cmd="run --select marts"))
    test_marts = BashOperator(
        task_id="dbt_test_marts",
        bash_command=DBT.format(cmd="test --select marts test_type:singular"),
        retries=0,
    )

    @task
    def trigger_alert_check(dq_summary: dict, **context) -> str:
        payload = {"event": "pipeline_succeeded", "run_id": context["run_id"], "ingestion": dq_summary}
        return _post_json(f"{N8N_WEBHOOK_BASE}/cc-sla-check", payload)

    dq = data_quality_gate(results)
    ingest >> dq >> source_freshness >> seed >> run_staging >> test_staging >> run_marts >> test_marts
    test_marts >> trigger_alert_check(dq)


customer_care_pipeline()
