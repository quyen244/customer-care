{{ config(materialized='view') }}

-- Urgent tickets that breached first-response SLA in the last 24h (answered late or still unanswered).
select
    l.ticket_id,
    l.status,
    l.is_open,
    l.created_at,
    l.first_response_due_at,
    l.first_response_at,
    coalesce(l.first_response_minutes,
             round((extract(epoch from now() - l.created_at) / 60)::numeric, 2)) as minutes_waited,
    l.first_response_target_minutes,
    c.company_name,
    c.segment,
    a.agent_name,
    a.team_name,
    cat.category_name,
    cat.subcategory_name,
    l.channel_key                                                              as channel
from {{ ref('v_sla_live') }} l
join {{ ref('dim_customer') }} c using (customer_id)
join {{ ref('dim_agent') }} a using (agent_id)
join {{ ref('dim_ticket_category') }} cat using (category_key)
where l.priority_key = 'urgent'
  and l.first_response_sla_status = 'breached'
  and l.created_at >= now() - interval '24 hours'
