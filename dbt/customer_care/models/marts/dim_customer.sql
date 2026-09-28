with revenue as (
    select
        customer_id,
        sum(net_revenue)                                   as lifetime_revenue,
        min(order_date)                                    as first_order_date,
        max(order_date) filter (where status = 'paid')     as last_paid_order_date,
        count(*) filter (where status = 'failed')          as failed_payments
    from {{ ref('stg_billing__sales_orders') }}
    group by 1
)
select
    c.customer_id,
    c.company_name,
    c.contact_name,
    c.email,
    c.segment,
    c.industry,
    c.region,
    c.country,
    c.plan_tier,
    c.billing_cycle,
    coalesce(c.account_manager, 'Unassigned (pooled)')     as account_manager,
    c.signup_date,
    c.churn_date,
    c.is_active,
    coalesce(r.lifetime_revenue, 0)                        as lifetime_revenue,
    r.first_order_date,
    r.last_paid_order_date,
    coalesce(r.failed_payments, 0)                         as failed_payments,
    c.updated_at
from {{ ref('stg_crm__customers') }} c
left join revenue r using (customer_id)

union all

-- Unknown member: tickets can reference a customer the CRM feed has not delivered yet.
select 'UNKNOWN', 'Unknown customer', null, null, 'Unknown', null, 'Unknown', null, null, null,
       'Unassigned (pooled)', null, null, true, 0, null, null, 0, null
