{{
    config(
        materialized='incremental',
        unique_key='ticket_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
        indexes=[
            {'columns': ['ticket_id'], 'unique': true},
            {'columns': ['created_date_key']},
            {'columns': ['first_response_sla_status']},
        ],
    )
}}

with tickets as (
    select * from {{ ref('fact_tickets') }}
    {% if is_incremental() %}
    where _loaded_at > (
            select coalesce(max(_loaded_at), '-infinity'::timestamptz) - interval '{{ var("incremental_lookback_hours", 2) }} hours'
            from {{ this }}
        )
       -- pending outcomes turn into breaches as time passes, without any new source row
       or ticket_id in (
            select ticket_id from {{ this }}
            where first_response_sla_status = 'pending' or resolution_sla_status = 'pending'
        )
    {% endif %}
),

evaluated as (
    select
        t.*,
        p.first_response_target_minutes,
        p.resolution_target_minutes,
        t.created_at + make_interval(mins => p.first_response_target_minutes) as first_response_due_at,
        t.created_at + make_interval(mins => p.resolution_target_minutes)     as resolution_due_at,
        {{ current_ts() }}                                                    as evaluated_at
    from tickets t
    join {{ ref('seed_sla_policy') }} p on p.priority = t.priority_key
)

select
    ticket_id,
    customer_id,
    agent_id,
    category_key,
    channel_key,
    priority_key,
    created_date_key,
    created_at,
    is_open,
    first_response_target_minutes,
    first_response_due_at,
    first_response_at,
    first_response_minutes,
    case
        when first_response_at is not null
            then case when first_response_minutes <= first_response_target_minutes then 'met' else 'breached' end
        when evaluated_at > first_response_due_at then 'breached'
        else 'pending'
    end                                                         as first_response_sla_status,
    resolution_target_minutes,
    resolution_due_at,
    resolved_at,
    resolution_minutes,
    case
        when resolved_at is not null and not is_open
            then case when resolution_minutes <= resolution_target_minutes then 'met' else 'breached' end
        when evaluated_at > resolution_due_at then 'breached'
        else 'pending'
    end                                                         as resolution_sla_status,
    evaluated_at,
    _loaded_at
from evaluated
