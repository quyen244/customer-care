-- Grain: one row per calendar day (UTC) from the first ticket until today.
with bounds as (
    select min(created_at)::date as first_day from {{ ref('fact_tickets') }}
),

days as (
    select d.date_key, d.date
    from {{ ref('dim_date') }} d, bounds b
    where d.date between b.first_day and current_date
),

created as (
    select
        s.created_date_key                                                            as date_key,
        count(*)                                                                      as tickets_created,
        count(*) filter (where s.priority_key = 'urgent')                             as urgent_created,
        count(*) filter (where s.first_response_sla_status = 'met')                   as first_response_sla_met,
        count(*) filter (where s.first_response_sla_status = 'breached')              as first_response_sla_breached,
        count(*) filter (where s.first_response_sla_status = 'pending')               as first_response_sla_pending,
        count(*) filter (where s.priority_key = 'urgent' and s.first_response_sla_status = 'breached') as urgent_sla_breached,
        count(*) filter (where s.resolution_sla_status = 'met')                       as resolution_sla_met,
        count(*) filter (where s.resolution_sla_status = 'breached')                  as resolution_sla_breached,
        round(avg(s.first_response_minutes), 2)                                       as avg_first_response_minutes,
        round((percentile_cont(0.5) within group (order by s.first_response_minutes))::numeric, 2) as median_first_response_minutes,
        count(*) filter (where t.is_reopened)                                         as tickets_reopened
    from {{ ref('fact_sla') }} s
    join {{ ref('fact_tickets') }} t using (ticket_id)
    group by 1
),

resolved as (
    select
        resolved_date_key                            as date_key,
        count(*)                                     as tickets_resolved,
        round(avg(resolution_minutes) / 60, 2)       as avg_resolution_hours
    from {{ ref('fact_tickets') }}
    where resolved_at is not null
    group by 1
),

csat as (
    select
        response_date_key                            as date_key,
        count(*)                                     as csat_responses,
        round(avg(score), 2)                         as avg_csat_score,
        count(*) filter (where is_satisfied)         as csat_satisfied
    from {{ ref('fact_csat') }}
    where is_responded
    group by 1
),

daily as (
    select
        d.date_key,
        d.date,
        coalesce(c.tickets_created, 0)               as tickets_created,
        coalesce(c.urgent_created, 0)                as urgent_created,
        coalesce(r.tickets_resolved, 0)              as tickets_resolved,
        coalesce(c.first_response_sla_met, 0)        as first_response_sla_met,
        coalesce(c.first_response_sla_breached, 0)   as first_response_sla_breached,
        coalesce(c.first_response_sla_pending, 0)    as first_response_sla_pending,
        coalesce(c.urgent_sla_breached, 0)           as urgent_sla_breached,
        coalesce(c.resolution_sla_met, 0)            as resolution_sla_met,
        coalesce(c.resolution_sla_breached, 0)       as resolution_sla_breached,
        c.avg_first_response_minutes,
        c.median_first_response_minutes,
        r.avg_resolution_hours,
        coalesce(c.tickets_reopened, 0)              as tickets_reopened,
        coalesce(cs.csat_responses, 0)               as csat_responses,
        cs.avg_csat_score,
        coalesce(cs.csat_satisfied, 0)               as csat_satisfied
    from days d
    left join created c using (date_key)
    left join resolved r using (date_key)
    left join csat cs using (date_key)
)

select
    *,
    round(100.0 * first_response_sla_met / nullif(first_response_sla_met + first_response_sla_breached, 0), 2)
                                                                            as first_response_sla_compliance_pct,
    round(100.0 * resolution_sla_met / nullif(resolution_sla_met + resolution_sla_breached, 0), 2)
                                                                            as resolution_sla_compliance_pct,
    round(100.0 * tickets_reopened / nullif(tickets_created, 0), 2)         as reopen_rate_pct,
    round(100.0 * csat_satisfied / nullif(csat_responses, 0), 2)            as csat_satisfied_pct,
    -- end-of-day backlog = everything created so far minus everything resolved so far
    sum(tickets_created) over (order by date) - sum(tickets_resolved) over (order by date)
                                                                            as open_backlog_eod
from daily
