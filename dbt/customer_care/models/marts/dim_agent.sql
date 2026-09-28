select
    agent_id,
    agent_name,
    email,
    team,
    case team
        when 'tier_1' then 'Tier 1 - General'
        when 'tier_2' then 'Tier 2 - Escalations'
        when 'technical' then 'Technical Support'
        when 'billing' then 'Billing & Accounts'
    end               as team_name,
    shift,
    hire_date,
    termination_date,
    is_active,
    updated_at
from {{ ref('stg_ticketing__agents') }}

union all

select 'UNASSIGNED', 'Unassigned', null, 'unassigned', 'Unassigned', null, null, null, true, null
