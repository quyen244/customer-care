select
    customer_id,
    trim(company_name)                                   as company_name,
    trim(contact_name)                                   as contact_name,
    lower(trim(email))                                   as email,
    phone,
    case lower(trim(segment))
        when 'smb' then 'SMB'
        when 'mid-market' then 'Mid-Market'
        when 'enterprise' then 'Enterprise'
    end                                                  as segment,
    industry,
    region,
    country,
    lower(trim(plan_tier))                               as plan_tier,
    lower(trim(billing_cycle))                           as billing_cycle,
    account_manager,
    signup_date,
    coalesce(is_active, true)                            as is_active,
    churn_date,
    updated_at,
    _loaded_at
from {{ source('raw', 'crm_customers') }}
