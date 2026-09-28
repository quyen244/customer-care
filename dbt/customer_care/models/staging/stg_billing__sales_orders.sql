select
    order_id,
    customer_id,
    order_date,
    lower(trim(plan))            as plan,
    lower(trim(order_type))      as order_type,
    lower(trim(billing_cycle))   as billing_cycle,
    amount,
    upper(trim(currency))        as currency,
    lower(trim(status))          as status,
    sales_rep,
    -- recognised revenue: paid orders count, refunded orders net to zero, failed never counted
    case lower(trim(status)) when 'paid' then amount else 0 end as net_revenue,
    updated_at,
    _loaded_at
from {{ source('raw', 'sales_orders') }}
