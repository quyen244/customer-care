# Upwork portfolio entry (copy and paste)

Lengths are checked against Upwork's limits: title 63/70, role 75/100, description 545/600, 5 skills.

## Project title

Customer Care Data Pipeline & SLA Dashboard (Airflow, dbt, n8n)

## Your role

Data Engineer: pipeline design, data modeling, dashboards, alerting, Docker

## Project description

Built an end-to-end data platform that shows Customer Care managers SLA compliance, backlog, response times, CSAT and agent productivity, and alerts them when SLAs slip.
- Ingests CRM API, ticketing, billing and CSAT data; validates every row and quarantines bad records
- PostgreSQL + dbt star schema with incremental models and 91 data tests
- Airflow runs it hourly with a data-quality gate, retries and failure alerts
- Metabase dashboards with 5 filters
- n8n sends email/Slack alerts on SLA breaches
- One command to run: docker compose up

## Skills and deliverables (5)

Apache Airflow, dbt, PostgreSQL, ETL Pipeline, Data Engineering

## Content (right-hand panel, in this order)

1. Video: `docs/demo/media/customer-care-demo.mp4`
2. Image: `docs/demo/media/sla-dashboard.gif`
3. Image: `artifacts/project-flow.png`
4. Image: `docs/demo/media/pipeline-run.gif`
5. Image: `docs/demo/media/alert-email.gif`
6. Link: the GitHub repository URL
