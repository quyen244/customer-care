{{ config(severity='warn') }}
-- Warn when >1% of tickets point at the UNKNOWN customer: the CRM feed is lagging or broken.
select count(*) filter (where customer_id = 'UNKNOWN') as unknown_customers, count(*) as total
from {{ ref('fact_tickets') }}
having count(*) filter (where customer_id = 'UNKNOWN') > 0.01 * count(*)
