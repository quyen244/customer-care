select
    s.survey_id,
    s.ticket_id,
    coalesce(t.customer_id, c.customer_id, 'UNKNOWN')                   as customer_id,
    coalesce(t.agent_id, 'UNASSIGNED')                                  as agent_id,
    coalesce(t.category_key, 'unknown/unspecified')                     as category_key,
    coalesce(t.channel_key, 'unknown')                                  as channel_key,
    t.priority_key,
    {{ date_key('s.sent_at') }}                                         as sent_date_key,
    {{ date_key('s.responded_at') }}                                    as response_date_key,
    s.sent_at,
    s.responded_at,
    s.is_responded,
    s.score,
    s.score >= 4                                                        as is_satisfied,
    s.score <= 2                                                        as is_dissatisfied,
    round((extract(epoch from s.responded_at - s.sent_at) / 3600.0)::numeric, 2) as response_lag_hours,
    sla.first_response_sla_status = 'breached'                          as first_response_sla_breached,
    coalesce(t.is_reopened, false)                                      as ticket_reopened,
    s.comment,
    s.updated_at
from {{ ref('stg_survey__csat') }} s
left join {{ ref('fact_tickets') }} t on t.ticket_id = s.ticket_id
left join {{ ref('fact_sla') }} sla on sla.ticket_id = s.ticket_id
left join {{ ref('dim_customer') }} c on c.customer_id = s.customer_id
