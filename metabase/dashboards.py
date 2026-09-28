"""Dashboard definitions as data: every card is plain SQL against the marts (see docs/dashboard_spec.md)."""

FILTERS = {
    "date": {"label": "Date range", "table": "dim_date", "column": "date", "widget": "date/all-options"},
    "category": {"label": "Category", "table": "dim_ticket_category", "column": "category_name", "widget": "string/="},
    "channel": {"label": "Channel", "table": "dim_channel", "column": "channel_name", "widget": "string/="},
    "priority": {"label": "Priority", "table": "dim_priority", "column": "priority_name", "widget": "string/="},
    "agent": {"label": "Agent", "table": "dim_agent", "column": "agent_name", "widget": "string/="},
}
ALL = ["date", "category", "channel", "priority", "agent"]
NO_DATE = ["category", "channel", "priority", "agent"]
COMPLIANCE = ("round(100.0 * count(*) FILTER (WHERE first_response_sla_status = 'met')\n"
              "      / nullif(count(*) FILTER (WHERE first_response_sla_status <> 'pending'), 0), 1)")


def star(fact: str, date_key: str | None = "created_date_key", filters=ALL) -> str:
    """FROM + dimension joins + field-filter WHERE. Tables stay unaliased so Metabase field filters resolve."""
    f = f"marts.{fact}"
    joins = [f"FROM {f}"]
    if date_key:
        joins.append(f"JOIN marts.dim_date ON marts.dim_date.date_key = {f}.{date_key}")
    joins += [
        f"JOIN marts.dim_ticket_category ON marts.dim_ticket_category.category_key = {f}.category_key",
        f"JOIN marts.dim_channel ON marts.dim_channel.channel_key = {f}.channel_key",
        f"JOIN marts.dim_priority ON marts.dim_priority.priority_key = {f}.priority_key",
        f"JOIN marts.dim_agent ON marts.dim_agent.agent_id = {f}.agent_id",
    ]
    where = " AND ".join("{{" + n + "}}" for n in filters)
    return "\n".join(joins) + f"\nWHERE {where}"


def kpi(name, sql, pos, filters=ALL, suffix=None, decimals=None, description=None):
    viz = {}
    if suffix:
        viz["scalar.suffix"] = suffix
    if decimals is not None:
        viz["scalar.decimals"] = decimals
    return {"name": name, "display": "scalar", "sql": sql, "filters": filters, "pos": pos, "viz": viz,
            "description": description}


def chart(name, display, pos, sql, dims, metrics, x_title=None, y_title=None, filters=ALL, **extra):
    viz = {"graph.dimensions": dims, "graph.metrics": metrics}
    if x_title is None:
        viz["graph.x_axis.labels_enabled"] = False
    else:
        viz["graph.x_axis.title_text"] = x_title
    if y_title:
        viz["graph.y_axis.title_text"] = y_title
    viz.update(extra)
    return {"name": name, "display": display, "pos": pos, "sql": sql, "filters": filters, "viz": viz}


def table(name, pos, sql, filters):
    return {"name": name, "display": "table", "pos": pos, "sql": sql, "filters": filters, "viz": {"table.pivot": False}}


SLA_OPERATIONS = {
    "name": "Customer Care - SLA Operations",
    "description": "Ticket volume, SLA compliance, response/resolution times, CSAT and agent productivity. All times UTC.",
    "filters": ALL,
    "default_date": "past30days~",
    "cards": [
        # ---- row 1: volume & SLA KPIs
        kpi("Total Tickets", f"SELECT count(*) AS total_tickets\n{star('fact_tickets')}", (0, 0, 4, 3),
            description="Tickets created in the selected period."),
        kpi("Open Tickets",
            f"SELECT count(*) AS open_tickets\n{star('fact_tickets', filters=NO_DATE)}\n  AND marts.fact_tickets.is_open",
            (4, 0, 4, 3), filters=NO_DATE,
            description="Current backlog: tickets new/open/pending/on hold, regardless of creation date."),
        kpi("SLA Compliance",
            f"SELECT {COMPLIANCE} AS sla_compliance_pct\n{star('fact_sla')}", (8, 0, 4, 3), suffix="%", decimals=1,
            description="First-response SLA: met / (met + breached). Tickets still inside their SLA window are excluded."),
        kpi("SLA Breaches",
            f"SELECT count(*) AS sla_breaches\n{star('fact_sla')}\n  AND first_response_sla_status = 'breached'",
            (12, 0, 4, 3), description="Tickets that missed their first-response target."),
        kpi("Avg First Response",
            f"SELECT round(avg(first_response_minutes), 1) AS avg_first_response_min\n{star('fact_tickets')}",
            (16, 0, 4, 3), suffix=" min", decimals=1),
        kpi("Avg Resolution",
            f"SELECT round(avg(resolution_minutes) / 60, 1) AS avg_resolution_hours\n{star('fact_tickets')}",
            (20, 0, 4, 3), suffix=" h", decimals=1, description="Created to (final) resolution, resolved tickets only."),
        # ---- row 2: quality & productivity KPIs
        kpi("CSAT Score",
            f"SELECT round(avg(score), 2) AS csat_score\n{star('fact_csat', 'response_date_key')}\n  AND is_responded",
            (0, 3, 4, 3), suffix=" / 5", decimals=2, description="Average survey score (1-5) by response date."),
        kpi("CSAT Satisfied",
            "SELECT round(100.0 * count(*) FILTER (WHERE is_satisfied) / nullif(count(*), 0), 1) AS csat_satisfied_pct\n"
            f"{star('fact_csat', 'response_date_key')}\n  AND is_responded",
            (4, 3, 4, 3), suffix="%", decimals=1, description="Share of responses scoring 4 or 5."),
        kpi("Reopen Rate",
            "SELECT round(100.0 * count(*) FILTER (WHERE is_reopened) / nullif(count(*), 0), 2) AS reopen_rate_pct\n"
            f"{star('fact_tickets')}", (8, 3, 4, 3), suffix="%", decimals=2,
            description="Share of tickets reopened after being resolved."),
        kpi("Tickets per Agent",
            "SELECT round(count(*)::numeric / nullif(count(DISTINCT marts.fact_tickets.agent_id), 0), 1) AS tickets_per_agent\n"
            f"{star('fact_tickets')}\n  AND marts.fact_tickets.agent_id <> 'UNASSIGNED'", (12, 3, 4, 3), decimals=1,
            description="Average tickets assigned per agent in the period."),
        kpi("Urgent Breaches",
            f"SELECT count(*) AS urgent_breaches\n{star('fact_sla')}\n"
            "  AND first_response_sla_status = 'breached' AND marts.fact_sla.priority_key = 'urgent'",
            (16, 3, 4, 3), description="Urgent tickets that missed the 15-minute first-response target."),
        kpi("Tickets Resolved",
            f"SELECT count(*) AS tickets_resolved\n{star('fact_tickets', 'resolved_date_key')}",
            (20, 3, 4, 3), description="Tickets resolved in the selected period."),
        # ---- row 3: trends
        chart("Ticket Volume by Date", "bar", (0, 6, 12, 6),
              'SELECT marts.dim_date.date AS "Date", marts.dim_priority.priority_name AS "Priority", count(*) AS "Tickets"\n'
              f"{star('fact_tickets')}\nGROUP BY 1, 2, marts.dim_priority.priority_rank\nORDER BY 1, marts.dim_priority.priority_rank",
              ["Date", "Priority"], ["Tickets"], x_title="Created date", y_title="Tickets",
              **{"stackable.stack_type": "stacked"}),
        chart("SLA Compliance by Day", "line", (12, 6, 12, 6),
              f'SELECT marts.dim_date.date AS "Date", {COMPLIANCE} AS "SLA compliance %"\n'
              f"{star('fact_sla')}\nGROUP BY 1\nORDER BY 1",
              ["Date"], ["SLA compliance %"], x_title="Created date", y_title="Compliance %",
              **{"graph.show_goal": True, "graph.goal_value": 90, "graph.goal_label": "Target 90%"}),
        # ---- row 4: breakdowns
        chart("Ticket Volume by Category", "row", (0, 12, 8, 7),
              'SELECT marts.dim_ticket_category.category_name AS "Category", count(*) AS "Tickets"\n'
              f"{star('fact_tickets')}\nGROUP BY 1\nORDER BY 2 DESC",
              ["Category"], ["Tickets"], y_title="Tickets", **{"graph.show_values": True}),
        chart("SLA Compliance by Priority", "bar", (8, 12, 8, 7),
              f'SELECT marts.dim_priority.priority_name AS "Priority", {COMPLIANCE} AS "SLA compliance %"\n'
              f"{star('fact_sla')}\nGROUP BY 1, marts.dim_priority.priority_rank\nORDER BY marts.dim_priority.priority_rank",
              ["Priority"], ["SLA compliance %"], x_title="Priority", y_title="Compliance %",
              **{"graph.show_goal": True, "graph.goal_value": 90, "graph.goal_label": "Target", "graph.show_values": True}),
        chart("First Response by Channel", "bar", (16, 12, 8, 7),
              'SELECT marts.dim_channel.channel_name AS "Channel", round(avg(first_response_minutes), 1) AS "Avg first response (min)"\n'
              f"{star('fact_tickets')}\nGROUP BY 1\nORDER BY 2",
              ["Channel"], ["Avg first response (min)"], x_title="Channel", y_title="Minutes",
              **{"graph.show_values": True}),
        # ---- row 5: backlog + CSAT trends
        chart("Ticket Backlog (end of day)", "line", (0, 19, 12, 6),
              'SELECT marts.mart_daily_sla_summary.date AS "Date", open_backlog_eod AS "Open backlog",\n'
              '       tickets_created AS "Created", tickets_resolved AS "Resolved"\n'
              "FROM marts.mart_daily_sla_summary\n"
              "JOIN marts.dim_date ON marts.dim_date.date_key = marts.mart_daily_sla_summary.date_key\n"
              "WHERE {{date}}\nORDER BY 1",
              ["Date"], ["Open backlog", "Created", "Resolved"], x_title="Date", y_title="Tickets", filters=["date"]),
        chart("CSAT Trend by Week", "line", (12, 19, 12, 6),
              'SELECT marts.dim_date.week_start_date AS "Week", round(avg(score), 2) AS "Avg CSAT (1-5)",\n'
              '       round(100.0 * count(*) FILTER (WHERE is_satisfied) / nullif(count(*), 0), 1) AS "Satisfied %"\n'
              f"{star('fact_csat', 'response_date_key')}\n  AND is_responded\nGROUP BY 1\nORDER BY 1",
              ["Week"], ["Avg CSAT (1-5)", "Satisfied %"], x_title="Response week",
              **{"series_settings": {"Satisfied %": {"axis": "right"}}}),
        # ---- row 6: agents
        table("Agent Productivity", (0, 25, 16, 9),
              'SELECT marts.dim_agent.agent_name AS "Agent", marts.dim_agent.team_name AS "Team",\n'
              '       sum(tickets_assigned) AS "Assigned", sum(tickets_resolved) AS "Resolved",\n'
              "       round(sum(tickets_resolved)::numeric / nullif(count(DISTINCT marts.fact_agent_performance.date_key) FILTER (WHERE tickets_resolved > 0), 0), 1) AS \"Resolved / active day\",\n"
              '       round(sum(avg_first_response_minutes * tickets_first_responded) / nullif(sum(tickets_first_responded), 0), 1) AS "Avg first response (min)",\n'
              '       round(100.0 * sum(sla_met) / nullif(sum(sla_met) + sum(sla_breached), 0), 1) AS "SLA %",\n'
              '       round(sum(avg_csat_score * csat_responses) / nullif(sum(csat_responses), 0), 2) AS "Avg CSAT",\n'
              '       sum(tickets_reopened) AS "Reopened"\n'
              "FROM marts.fact_agent_performance\n"
              "JOIN marts.dim_date ON marts.dim_date.date_key = marts.fact_agent_performance.date_key\n"
              "JOIN marts.dim_agent ON marts.dim_agent.agent_id = marts.fact_agent_performance.agent_id\n"
              "WHERE {{date}} AND {{agent}} AND marts.dim_agent.agent_id <> 'UNASSIGNED'\n"
              'GROUP BY 1, 2\nORDER BY "Resolved" DESC',
              ["date", "agent"]),
        chart("Top Agents by Tickets", "row", (16, 25, 8, 9),
              'SELECT marts.dim_agent.agent_name AS "Agent", count(*) AS "Tickets"\n'
              f"{star('fact_tickets')}\n  AND marts.fact_tickets.agent_id <> 'UNASSIGNED'\nGROUP BY 1\nORDER BY 2 DESC\nLIMIT 15",
              ["Agent"], ["Tickets"], y_title="Tickets", **{"graph.show_values": True}),
    ],
}

DQ_DATE = "JOIN marts.dim_date ON marts.dim_date.date = {expr}\nWHERE {{{{date}}}}"
LABEL = "replace(replace(initcap(replace({col}, '_', ' ')), 'Crm', 'CRM'), 'Csat', 'CSAT')"

PIPELINE_HEALTH = {
    "name": "Customer Care - Data Quality & Alerts",
    "description": "Ingestion runs, quarantined records by reason, and every alert n8n has sent.",
    "filters": ["date"],
    "default_date": "past7days~",
    "cards": [
        chart("Rejected Records by Reason", "row", (0, 0, 12, 7),
              f'SELECT {LABEL.format(col="data_quality.rejected_records.reason")} AS "Reason",\n'
              f'       {LABEL.format(col="data_quality.rejected_records.source")} AS "Source", count(*) AS "Records"\n'
              "FROM data_quality.rejected_records\n"
              + DQ_DATE.format(expr="(data_quality.rejected_records.rejected_at AT TIME ZONE 'UTC')::date")
              + "\nGROUP BY 1, 2\nORDER BY 3 DESC",
              ["Reason", "Source"], ["Records"], y_title="Rejected records",
              filters=["date"], **{"stackable.stack_type": "stacked"}),
        chart("Rows Loaded per Day by Source", "bar", (12, 0, 12, 7),
              'SELECT marts.dim_date.date AS "Date",\n'
              f'       {LABEL.format(col="data_quality.ingestion_runs.source")} AS "Source", sum(rows_loaded) AS "Rows loaded"\n'
              "FROM data_quality.ingestion_runs\n"
              + DQ_DATE.format(expr="(data_quality.ingestion_runs.started_at AT TIME ZONE 'UTC')::date")
              + " AND status = 'success'\nGROUP BY 1, 2\nORDER BY 1",
              ["Date", "Source"], ["Rows loaded"], x_title="Load date", y_title="Rows loaded",
              filters=["date"], **{"stackable.stack_type": "stacked", "graph.x_axis.scale": "ordinal"}),
        table("Source Freshness", (0, 7, 10, 6),
              f'SELECT {LABEL.format(col="source")} AS "Source",\n'
              '       max(finished_at) FILTER (WHERE status = \'success\') AS "Last successful load",\n'
              '       round(extract(epoch FROM now() - max(finished_at) FILTER (WHERE status = \'success\')) / 60) AS "Minutes ago",\n'
              '       count(*) FILTER (WHERE status = \'failed\' AND started_at > now() - interval \'24 hours\') AS "Failures (24h)"\n'
              "FROM data_quality.ingestion_runs\nGROUP BY 1\nORDER BY 1",
              []),
        table("Ingestion Runs", (10, 7, 14, 6),
              'SELECT started_at AS "Started", data_quality.ingestion_runs.source AS "Source", status AS "Status",\n'
              '       source_file AS "File", rows_read AS "Read", rows_loaded AS "Loaded", rows_rejected AS "Rejected",\n'
              '       rows_duplicate AS "Duplicates", round(extract(epoch FROM finished_at - started_at)::numeric, 2) AS "Seconds",\n'
              '       error AS "Error"\n'
              "FROM data_quality.ingestion_runs\n"
              + DQ_DATE.format(expr="(data_quality.ingestion_runs.started_at AT TIME ZONE 'UTC')::date")
              + "\nORDER BY started_at DESC\nLIMIT 200",
              ["date"]),
        table("Alerts Sent", (0, 13, 24, 7),
              'SELECT sent_at AS "Sent", alert_type AS "Type", severity AS "Severity", alert_key AS "Key",\n'
              '       message AS "Message", array_to_string(channels, \', \') AS "Channels"\n'
              "FROM alerting.alert_log\n"
              + DQ_DATE.format(expr="(alerting.alert_log.sent_at AT TIME ZONE 'UTC')::date")
              + "\nORDER BY sent_at DESC",
              ["date"]),
    ],
}

DASHBOARDS = [SLA_OPERATIONS, PIPELINE_HEALTH]
