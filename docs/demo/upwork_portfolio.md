# Upwork portfolio entry (copy and paste)

## Project title

Customer Care Data Pipeline & SLA Dashboard (Airflow, dbt, PostgreSQL, Metabase, n8n)

## Your role

Data Engineer (end-to-end: data modeling, pipelines, dashboards, alerting, Docker)

## Project description

Built an end-to-end data platform that gives Customer Care managers live visibility into SLA compliance, backlog, response times, CSAT and agent productivity, and alerts them the moment SLAs slip.

- Ingests CRM (REST API), ticketing, billing and CSAT data, validating every row and quarantining bad records (nulls, duplicates, invalid timestamps and statuses) with the reason.
- Loads PostgreSQL idempotently and incrementally, then models a star schema with dbt (5 dimensions, 4 facts, 90 data tests plus an SLA unit test).
- Orchestrates everything hourly with Airflow, with a data-quality gate, retries and failure alerts that name the exact failing test.
- Metabase dashboards with date, category, channel, priority and agent filters, plus a data-quality dashboard.
- n8n alerts by email or Slack when SLA compliance drops below target, the backlog grows too large, or an urgent ticket breaches its SLA, with dedup and cooldown.
- Runs anywhere with a single docker compose up; dashboards, workflows and database roles are all provisioned as code.

## Skills (Upwork tags)

Data Engineering, ETL Pipeline, Apache Airflow, dbt, PostgreSQL, SQL, Python, Data Modeling, Metabase, n8n, Docker, Data Visualization, Dashboard

## Media to upload (in this order)

1. `docs/demo/media/customer-care-demo.mp4` (or a YouTube/Vimeo link to it) as the main video.
2. `docs/demo/media/sla-dashboard.gif`
3. `docs/demo/media/architecture.png`
4. `docs/demo/media/pipeline-run.gif`
5. `docs/demo/media/alert-email.gif`
6. `docs/demo/media/data-quality.gif`
