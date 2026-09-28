with channels as (
    select distinct channel from {{ ref('stg_ticketing__tickets') }}
    union
    select unnest(array['email', 'chat', 'phone', 'web_form', 'social', 'unknown'])
)
select
    channel                                     as channel_key,
    initcap(replace(channel, '_', ' '))         as channel_name,
    case
        when channel in ('phone', 'chat') then 'Real-time'
        when channel in ('email', 'web_form', 'social') then 'Asynchronous'
        else 'Unknown'
    end                                         as channel_type
from channels
