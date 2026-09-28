{{ config(indexes=[{'columns': ['agent_id', 'date_key'], 'unique': true}]) }}

-- Grain: agent x day. Each activity is counted on the day it happened.
with events as (
    select agent_id, created_date_key as date_key,
           1 as assigned, 0 as first_responded, null::numeric as frt_min, 0 as resolved,
           null::numeric as resolution_min, 0 as reopened
    from {{ ref('fact_tickets') }}

    union all
    select agent_id, {{ date_key('first_response_at') }}, 0, 1, first_response_minutes, 0, null, 0
    from {{ ref('fact_tickets') }} where first_response_at is not null

    union all
    select agent_id, resolved_date_key, 0, 0, null, 1, resolution_minutes, 0
    from {{ ref('fact_tickets') }} where resolved_at is not null

    union all
    select agent_id, {{ date_key('reopened_at') }}, 0, 0, null, 0, null, 1
    from {{ ref('fact_tickets') }} where reopened_at is not null
),

activity as (
    select
        agent_id,
        date_key,
        sum(assigned)                         as tickets_assigned,
        sum(first_responded)                  as tickets_first_responded,
        round(avg(frt_min), 2)                as avg_first_response_minutes,
        sum(resolved)                         as tickets_resolved,
        round(avg(resolution_min) / 60, 2)    as avg_resolution_hours,
        sum(reopened)                         as tickets_reopened
    from events
    group by 1, 2
),

sla as (
    select
        agent_id,
        created_date_key                                                   as date_key,
        count(*) filter (where first_response_sla_status = 'met')          as sla_met,
        count(*) filter (where first_response_sla_status = 'breached')     as sla_breached
    from {{ ref('fact_sla') }}
    group by 1, 2
),

csat as (
    select
        agent_id,
        response_date_key                                as date_key,
        count(*)                                         as csat_responses,
        round(avg(score), 2)                             as avg_csat_score,
        count(*) filter (where is_satisfied)             as csat_satisfied
    from {{ ref('fact_csat') }}
    where is_responded
    group by 1, 2
)

select
    a.agent_id,
    a.date_key,
    a.tickets_assigned,
    a.tickets_first_responded,
    a.avg_first_response_minutes,
    a.tickets_resolved,
    a.avg_resolution_hours,
    a.tickets_reopened,
    coalesce(s.sla_met, 0)                                                 as sla_met,
    coalesce(s.sla_breached, 0)                                            as sla_breached,
    round(100.0 * s.sla_met / nullif(s.sla_met + s.sla_breached, 0), 2)    as sla_compliance_pct,
    coalesce(c.csat_responses, 0)                                          as csat_responses,
    c.avg_csat_score,
    coalesce(c.csat_satisfied, 0)                                          as csat_satisfied
from activity a
left join sla s using (agent_id, date_key)
left join csat c using (agent_id, date_key)
