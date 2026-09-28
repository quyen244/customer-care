{{
    config(
        materialized='incremental',
        unique_key='ticket_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
        indexes=[
            {'columns': ['ticket_id'], 'unique': true},
            {'columns': ['created_date_key']},
            {'columns': ['agent_id']},
        ],
    )
}}

with tickets as (
    select * from {{ ref('stg_ticketing__tickets') }}
    {% if is_incremental() %}
    where _loaded_at > (
            select coalesce(max(_loaded_at), '-infinity'::timestamptz) - interval '{{ var("incremental_lookback_hours", 2) }} hours'
            from {{ this }}
        )
       -- late-arriving dimensions: retry resolution of unknown members every run
       or ticket_id in (select ticket_id from {{ this }} where customer_id = 'UNKNOWN' or agent_id = 'UNASSIGNED')
    {% endif %}
)

select
    t.ticket_id,
    coalesce(c.customer_id, 'UNKNOWN')                         as customer_id,
    coalesce(a.agent_id, 'UNASSIGNED')                         as agent_id,
    coalesce(cat.category_key, 'unknown/unspecified')          as category_key,
    t.channel                                                  as channel_key,
    t.priority                                                 as priority_key,
    {{ date_key('t.created_at') }}                             as created_date_key,
    {{ date_key('t.resolved_at') }}                            as resolved_date_key,
    t.subject,
    t.status,
    t.is_open,
    t.reopen_count > 0                                         as is_reopened,
    t.reopen_count,
    t.created_at,
    t.first_response_at,
    t.resolved_at,
    t.closed_at,
    t.reopened_at,
    {{ minutes_between('t.created_at', 't.first_response_at') }} as first_response_minutes,
    {{ minutes_between('t.created_at', 't.resolved_at') }}       as resolution_minutes,
    t.updated_at,
    t._loaded_at
from tickets t
left join {{ ref('dim_customer') }} c on c.customer_id = t.customer_id
left join {{ ref('dim_agent') }} a on a.agent_id = t.agent_id
left join {{ ref('dim_ticket_category') }} cat
    on cat.category_key = t.category || '/' || coalesce(t.subcategory, 'unspecified')
