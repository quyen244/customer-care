select
    priority                                   as priority_key,
    initcap(priority)                          as priority_name,
    priority_rank,
    first_response_target_minutes,
    resolution_target_minutes
from {{ ref('seed_sla_policy') }}
