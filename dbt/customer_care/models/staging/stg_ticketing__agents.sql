select
    agent_id,
    trim(agent_name)          as agent_name,
    lower(trim(email))        as email,
    lower(trim(team))         as team,
    lower(trim(shift))        as shift,
    hire_date,
    termination_date,
    coalesce(is_active, termination_date is null) as is_active,
    updated_at,
    _loaded_at
from {{ source('raw', 'agents') }}
