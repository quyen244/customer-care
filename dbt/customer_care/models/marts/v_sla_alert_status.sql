{{ config(materialized='view') }}

-- Single-row health snapshot polled by n8n. Rolling 24h window avoids a noisy "today" right after midnight.
with live as (
    select * from {{ ref('v_sla_live') }}
),

window_24h as (
    select * from live where created_at >= now() - interval '24 hours'
)

select
    now()                                                                           as evaluated_at,
    (select max(_loaded_at) from {{ ref('fact_tickets') }})                        as data_loaded_through,
    (select count(*) from window_24h)                                               as tickets_created_24h,
    (select count(*) from window_24h where first_response_sla_status = 'met')       as sla_met_24h,
    (select count(*) from window_24h where first_response_sla_status = 'breached')  as sla_breached_24h,
    (select round(100.0 * count(*) filter (where first_response_sla_status = 'met')
                  / nullif(count(*) filter (where first_response_sla_status <> 'pending'), 0), 2)
       from window_24h)                                                             as sla_compliance_pct_24h,
    (select count(*) from live where is_open)                                       as open_backlog,
    (select count(*) from live where is_open and priority_key in ('urgent', 'high')) as open_backlog_urgent_high,
    (select count(*) from window_24h
      where priority_key = 'urgent' and first_response_sla_status = 'breached')     as urgent_breached_24h,
    (select count(*) from live
      where priority_key = 'urgent' and first_response_sla_status = 'breached' and is_open) as urgent_breached_open
