{{ config(materialized='view') }}

-- Same SLA rules as fact_sla, but evaluated at query time so alert checks between dbt runs stay current.
select
    t.ticket_id,
    t.customer_id,
    t.agent_id,
    t.category_key,
    t.channel_key,
    t.priority_key,
    t.status,
    t.is_open,
    t.created_at,
    t.first_response_at,
    t.first_response_minutes,
    p.first_response_target_minutes,
    t.created_at + make_interval(mins => p.first_response_target_minutes) as first_response_due_at,
    case
        when t.first_response_at is not null
            then case when t.first_response_minutes <= p.first_response_target_minutes then 'met' else 'breached' end
        when now() > t.created_at + make_interval(mins => p.first_response_target_minutes) then 'breached'
        else 'pending'
    end                                                                    as first_response_sla_status
from {{ ref('fact_tickets') }} t
join {{ ref('seed_sla_policy') }} p on p.priority = t.priority_key
