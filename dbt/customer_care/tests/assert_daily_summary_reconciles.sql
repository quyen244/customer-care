-- Daily summary totals must reconcile with the ticket fact (no rows lost or double counted).
with summary as (select sum(tickets_created) as n from {{ ref('mart_daily_sla_summary') }}),
     facts as (select count(*) as n from {{ ref('fact_tickets') }} where created_at::date <= current_date)
select summary.n as summary_total, facts.n as fact_total
from summary, facts
where summary.n <> facts.n
