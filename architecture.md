# Customer Care Data & SLA Intelligence Platform - Architecture

## 1. Purpose

This project simulates a realistic Customer Care analytics stack.
Several upstream business systems (CRM, ticketing, sales, CSAT surveys) feed raw data into a warehouse.
dbt transforms that raw data into a governed star schema.
An operational dashboard shows ticket, SLA and CSAT health for Customer Care management.
n8n alerts the team when SLA thresholds are breached.
Everything runs locally via Docker Compose, but every component maps 1:1 to what a real Customer Care data team would run in production.

## 2. System diagram

```
+--------------+  +--------------+  +--------------+  +--------------+
| CRM API/CSV  |  | Ticketing    |  | Sales CSV    |  | CSAT CSV     |
| customers,   |  | tickets,     |  | orders,      |  | post-        |
| accounts     |  | agents       |  | plans, MRR   |  | resolution   |
+------+-------+  +------+-------+  +------+-------+  +------+-------+
       |                 |                 |                 |
       +--------+--------+--------+--------+--------+--------+
                         |
                         v
            +--------------------------+
            | Python ingestion         |  - validate: nulls, duplicates,
            | batch_id, idempotent     |    invalid timestamps, invalid status
            | upsert, structured logs  |  - bad rows -> quarantine table
            +------------+-------------+
                         v
            +--------------------------+
            | PostgreSQL: raw.*        |  1 table per source, upsert on natural key
            | + data_quality.*         |  + rejected_records, ingestion_runs
            +------------+-------------+
                         v
            +--------------------------+
            | dbt staging (views)      |  typed, deduplicated, enums standardized
            +------------+-------------+
                         v
            +--------------------------+
            | dbt marts (star schema)  |  dims + facts, SLA/CSAT/reopen logic
            +------------+-------------+
                         v
        +----------------+-----------------+
        v                                  v
+------------------+            +--------------------+
| Metabase         |            | n8n                |
| dashboards,      |            | SLA / backlog /    |
| filters          |            | urgent-breach      |
| (Power BI can    |            | alerts -> Slack /  |
| use same marts)  |            | email              |
+------------------+            +--------------------+

Orchestration: Airflow DAG = generate -> ingest -> dbt seed/run -> dbt test -> trigger n8n webhook
```

## 3. Tool choices and why

**PostgreSQL** hosts the warehouse in one instance to keep the stack light.
Schemas: `raw` (landing), `staging` and `marts` (owned by dbt), `data_quality` (quarantine + run log).
A second database, `airflow`, backs Airflow metadata, and a third, `n8n`, backs n8n.

**Python ingestion** owns extract, load and row-level validation.
dbt assumes rows are already landed, so validation of malformed source rows belongs before `raw`, which is the realistic production split.

**dbt** owns everything from staging onward, including the data quality tests that gate promotion to marts.

**Airflow 3.3** runs with `LocalExecutor` in three containers (API server, scheduler, DAG processor) sharing one custom image; dbt lives in its own virtualenv inside it.
That is enough to show scheduling, retries and task logs without a Celery/Redis cluster, which would be overkill here.

**Metabase** is used instead of Power BI.
Power BI Desktop is Windows-only and Power BI Report Server is not realistically dockerizable for a local demo.
Metabase is open-source, small, and connects to Postgres natively.
The dashboard spec (`docs/dashboard_spec.md`) defines every chart as a plain SQL query against `marts`, so pointing Power BI's Postgres connector at the same schema reproduces it.

**n8n** hosts the alert workflow (`n8n/workflows/sla_alert_workflow.json`).
It runs on a schedule and is also triggered by Airflow via webhook after each successful `dbt test`.

## 4. Layering contract

| Layer | Schema | Owner | Contract |
|---|---|---|---|
| Landing | `raw` | Python ingestion | One row per source record, upserted on the natural key, plus `_batch_id` and `_loaded_at`. |
| Quarantine | `data_quality.rejected_records` | Python ingestion | Rows that failed validation, with a reason code. Bad data never reaches `raw`. |
| Run log | `data_quality.ingestion_runs` | Python ingestion | One row per source per run: rows read, loaded, rejected, status. |
| Staging | `staging` | dbt | One view per raw table: cast, trimmed, enums standardized (duplicates are already removed at ingestion). |
| Marts | `marts` | dbt | Star schema and business logic (SLA, reopen, CSAT). Facts are incremental. |
| Quality gate | dbt tests | dbt | `dbt test` fails the Airflow task, so bad data blocks alerts downstream. |

## 5. Idempotency and incrementality

Each ingestion run gets a `batch_id` (UUID).
Rows are upserted with `INSERT ... ON CONFLICT (natural_key) DO UPDATE`, so re-running the same file does not duplicate rows.
The update only fires when the source `updated_at` is newer or equal, so a stale re-delivery cannot overwrite fresher data.

`fact_tickets` and `fact_sla` are dbt incremental models with `unique_key = ticket_id` and a `updated_at` watermark.
Daily runs reprocess only tickets touched since the last run, while status changes (for example a reopen) still update the existing row via merge.
Dimensions are small and rebuilt as tables each run.
They are current-state only (SCD1); SCD2 history is a noted extension, not in scope.

## 6. Data model (star schema)

```
                      dim_date
                         |
 dim_customer ---- fact_tickets ---- dim_agent
                    |    |    \
       dim_channel -+    |     +- dim_ticket_category
                         |
          fact_sla (1:1 ticket)   fact_csat (0..1 per ticket)

 fact_agent_performance: grain = agent x day, aggregated from fact_tickets / fact_sla / fact_csat
 mart_daily_sla_summary: grain = day, feeds n8n alerts and dashboard KPI tiles
```

### Dimensions

| Table | Grain | Key columns |
|---|---|---|
| `dim_customer` | one row per customer | customer_id, company_name, segment (SMB/Mid-Market/Enterprise), region, plan_tier, lifetime_revenue, is_active |
| `dim_agent` | one row per support agent | agent_id, agent_name, team (Tier 1/Tier 2/Billing/Technical), hire_date, is_active |
| `dim_date` | one row per calendar day | date_key (YYYYMMDD), date, day_of_week, week, month, quarter, year, is_weekend |
| `dim_ticket_category` | one row per category/subcategory | category_key, category, subcategory |
| `dim_channel` | one row per channel | channel_key, channel (email/chat/phone/web_form/social) |

### Facts

| Table | Grain | Measures |
|---|---|---|
| `fact_tickets` | one row per ticket (current state) | created/first_response/resolved/closed timestamps, status, priority, reopen_count, is_open, is_reopened |
| `fact_sla` | one row per ticket | first_response_minutes, sla_target_minutes, sla_breached, resolution_minutes, resolution_sla_target_minutes, resolution_sla_breached |
| `fact_csat` | one row per survey response | score (1-5), is_satisfied (score >= 4), response lag |
| `fact_agent_performance` | one row per agent per day | tickets_assigned, tickets_resolved, avg_first_response_minutes, sla_compliance_pct, avg_csat |

## 7. SLA policy

SLA thresholds live in a dbt seed (`seeds/seed_sla_policy.csv`), not hardcoded SQL, so they are versioned, queryable and testable.

| Priority | First response | Resolution |
|---|---|---|
| urgent | 15 min | 4 h |
| high | 60 min | 24 h |
| medium | 240 min | 72 h |
| low | 480 min | 120 h |

A ticket that has not yet received a first response is counted as breached once its age exceeds the target.
This matters operationally: an unanswered urgent ticket is the most important breach to alert on, and ignoring open tickets would hide it.

## 8. Alerting logic (n8n)

Triggered every 15 minutes and by Airflow after each successful pipeline run.
It queries `marts.mart_daily_sla_summary` and `marts.fact_sla`, then fires when any condition holds:

1. Today's first-response SLA compliance is below 90%.
2. Open ticket backlog exceeds `BACKLOG_THRESHOLD` (default 350; a normal day runs 270-360).
3. Any urgent ticket has breached its SLA and is still open.

One message lists every condition that fired with the offending numbers, so on-call can judge severity without opening the dashboard.
Email goes to Mailpit, a local inbox at http://localhost:8025; Slack is used when `SLACK_WEBHOOK_URL` is set.
Every alert is recorded in `alerting.alert_log`, which also drives dedup (one alert per urgent ticket) and a cooldown for the rate-based alerts.
A second workflow emails pipeline failures sent by Airflow's failure callback, naming the failing dbt test.

## 9. Synthetic dataset design

The generator (`data_generator/generate_data.py`) produces data with the shapes a real Customer Care team sees, not uniform random noise.

| Source | File | Rows (default) | Realism built in |
|---|---|---|---|
| CRM | REST API (`/api/v1/customers`) | ~1,500 | Segment mix 60/30/10 (SMB/Mid/Ent), regions, signup dates over 3 years |
| Ticketing | `agents.csv` | 45 | Teams, shifts, some inactive (churned) agents |
| Ticketing | `tickets.csv` | ~23,000 over 180 days | Weekday peaks, business-hour peaks, Monday spike, enterprise customers get more urgent tickets, response time depends on priority, channel and agent skill, ~7% breach urgent SLA, ~6% reopened, recent tickets still open |
| Sales | `sales_orders.csv` | ~10,000 | Plan upgrades/renewals, links customers to revenue for segment analysis |
| CSAT | `csat_surveys.csv` | ~35% response rate on resolved tickets | Score correlates with SLA breach and resolution time |

Data quality defects are injected on purpose at a low rate (about 1-2%), so validation has real work to do:
null required fields, exact duplicate rows, `resolved_at` before `created_at`, unparseable timestamps, and unknown status values like `in-progres`.

## 10. Folder structure

```
project-2-customer-care-data/
|-- architecture.md
|-- README.md
|-- docker-compose.yml
|-- .env.example
|-- data_generator/          synthetic CRM / ticket / sales / CSAT data
|-- ingestion/               CSV -> validation -> raw.* (idempotent upsert)
|-- sql/                     Postgres init: databases, schemas, raw + data_quality DDL
|-- dbt/customer_care/       staging + marts + tests + SLA seed
|-- airflow/                 Dockerfile + DAG
|-- n8n/workflows/           importable alert workflow
|-- metabase/                dashboards as code + provisioning script (API)
`-- docs/                    dashboard spec, demo video, slides, recorder
```

## 11. Out of scope

SCD2 history on dimensions.
Row-level security and multi-tenant access.
Real Slack/email credentials (placeholders provided).
Streaming ingestion (batch every hour is realistic for SLA reporting at this scale).

## 12. Data-quality gate

After ingestion, Airflow fails the run when rejects look systemic rather than random.
A batch of 100+ rows fails above a 5% reject rate (`MAX_REJECT_RATE`).
A smaller batch fails only when at least 5 rows and over half of it are rejected, because one bad row in a 9-row incremental file is 11% but harmless.
