# Dashboard Specification

This spec defines the operational dashboards for Customer Care management.
It is tool-agnostic: every card is a plain SQL query against the `marts` schema, so it can be rebuilt in Power BI, Tableau or Superset.
The Metabase implementation is generated from `metabase/dashboards.py` by `metabase/bootstrap_metabase.py`, so this document and the running dashboard stay in sync.

## Audience and questions

| Audience | Question the dashboard must answer in under 10 seconds |
|---|---|
| Customer Care manager | Are we meeting our SLAs today and this month, and where are we failing? |
| Team lead | Which agents are overloaded or slow, and is quality (CSAT, reopens) holding up? |
| Workforce planner | When does volume peak, and is the backlog growing or shrinking? |
| Data team | Is the data fresh and trustworthy, and what did validation reject? |

## Conventions

All timestamps and dates are UTC.
Ticket metrics are attributed to the ticket's **created** date, resolution counts to the **resolved** date, and CSAT to the survey **response** date.
SLA compliance is `met / (met + breached)`.
Tickets still inside their SLA window (`pending`) are excluded until decided, so a young ticket never counts as a success or a failure too early.
An unanswered ticket past its due time counts as `breached` immediately, even before anyone responds.

## Global filters

Every filter is wired to every card where it is meaningful.

| Filter | Field | Default | Notes |
|---|---|---|---|
| Date range | `dim_date.date` | Past 30 days including today | Joined on the date that matches each card's grain (created, resolved or response date). |
| Category | `dim_ticket_category.category_name` | All | Billing, Technical, Account, Onboarding, Feature Request, Cancellation, General Inquiry. |
| Channel | `dim_channel.channel_name` | All | Email, Chat, Phone, Web Form, Social. |
| Priority | `dim_priority.priority_name` | All | Urgent, High, Medium, Low. |
| Agent | `dim_agent.agent_name` | All | |

"Open Tickets (backlog now)" deliberately ignores the date filter: backlog is a point-in-time state, and old unresolved tickets are exactly the ones a manager must see.

## Dashboard 1: Customer Care - SLA Operations

### KPI tiles (rows 1-2)

| Metric | Definition | Source |
|---|---|---|
| Total Tickets | Count of tickets created in range | `fact_tickets` |
| Open Tickets (backlog now) | Tickets with status new, open, pending or on_hold | `fact_tickets.is_open` |
| SLA Compliance (first response) | met / (met + breached) | `fact_sla.first_response_sla_status` |
| SLA Breaches | Count of first-response breaches | `fact_sla` |
| Avg First Response | Mean minutes from created to first agent reply | `fact_tickets.first_response_minutes` |
| Avg Resolution Time | Mean hours from created to final resolution | `fact_tickets.resolution_minutes` |
| CSAT Score | Mean survey score, 1-5 | `fact_csat.score` |
| CSAT Satisfied | Share of responses scoring 4 or 5 | `fact_csat.is_satisfied` |
| Reopen Rate | Share of tickets reopened at least once | `fact_tickets.is_reopened` |
| Avg Tickets per Agent | Tickets / distinct assigned agents | `fact_tickets` |
| Urgent SLA Breaches | Urgent tickets that breached first response | `fact_sla` |
| Tickets Resolved | Tickets resolved in range (resolved date) | `fact_tickets.resolved_date_key` |

### Charts

| Card | Type | Why it is there |
|---|---|---|
| Ticket Volume by Date | Stacked bar, by priority | Shows Monday peaks, weekend dips and incident spikes, and whether the spike was urgent work. |
| SLA Compliance by Day | Line with 90% goal line | Pinpoints the exact days the team fell below target. |
| Ticket Volume by Category | Horizontal bar | Where demand comes from; drives staffing by skill. |
| SLA Compliance by Priority | Bar with goal line | Urgent failures matter most, so they must not hide inside a healthy average. |
| Avg First Response by Channel | Bar | Validates channel expectations (phone/chat minutes, email hours). |
| Ticket Backlog (end of day) | Line: backlog, created, resolved | Backlog grows when created exceeds resolved; this is the leading indicator of future breaches. |
| CSAT Trend by Week | Line: avg score + satisfied % (right axis) | Weekly smooths daily survey noise. |
| Agent Productivity | Table | Assigned, resolved, resolved per active day, avg first response, SLA %, CSAT, reopens per agent. |
| Tickets per Agent | Horizontal bar, top 15 | Load balance across the team. |

Agent productivity uses **resolved per active day** rather than raw totals, so part-time, new or departed agents are compared fairly.
Weighted averages (first response, CSAT) are recomputed from counts, never averaged from daily averages.

### Example SQL (SLA Compliance by Priority)

Every ticket card uses the same star join; field filters expand to `1 = 1` when empty.

```sql
SELECT marts.dim_priority.priority_name AS priority,
       round(100.0 * count(*) FILTER (WHERE first_response_sla_status = 'met')
             / nullif(count(*) FILTER (WHERE first_response_sla_status <> 'pending'), 0), 1) AS sla_compliance_pct
FROM marts.fact_sla
JOIN marts.dim_date ON marts.dim_date.date_key = marts.fact_sla.created_date_key
JOIN marts.dim_ticket_category ON marts.dim_ticket_category.category_key = marts.fact_sla.category_key
JOIN marts.dim_channel ON marts.dim_channel.channel_key = marts.fact_sla.channel_key
JOIN marts.dim_priority ON marts.dim_priority.priority_key = marts.fact_sla.priority_key
JOIN marts.dim_agent ON marts.dim_agent.agent_id = marts.fact_sla.agent_id
WHERE {{date}} AND {{category}} AND {{channel}} AND {{priority}} AND {{agent}}
GROUP BY 1, marts.dim_priority.priority_rank
ORDER BY marts.dim_priority.priority_rank;
```

## Dashboard 2: Customer Care - Data Quality & Alerts

| Card | Purpose |
|---|---|
| Rejected Records by Reason | Quarantined rows by source and reason (null fields, invalid status, bad timestamps, duplicates). |
| Rows Loaded per Day by Source | Volume per feed; a sudden drop means a broken export. |
| Source Freshness | Last successful load per source and failures in the last 24h. |
| Ingestion Runs | Per-file audit trail: rows read, loaded, rejected, duplicates, duration, error. |
| Alerts Sent | Every alert n8n delivered, with severity, message and channels. |

Default range is the past 7 days including today.

## Porting to Power BI

1. Connect Power BI Desktop to PostgreSQL at `localhost:5433`, database `customer_care`, user `bi_reader`.
2. Import the `marts` tables (DirectQuery also works at this volume).
3. Relationships: facts to `dim_date[date_key]`, `dim_customer[customer_id]`, `dim_agent[agent_id]`, `dim_ticket_category[category_key]`, `dim_channel[channel_key]`, `dim_priority[priority_key]`, all many-to-one, single direction.
4. Recreate the measures from the definitions above, for example `SLA Compliance % = DIVIDE(CALCULATE(COUNTROWS(fact_sla), fact_sla[first_response_sla_status] = "met"), CALCULATE(COUNTROWS(fact_sla), fact_sla[first_response_sla_status] <> "pending"))`.
5. Use the dimension columns listed under Global filters as slicers.
