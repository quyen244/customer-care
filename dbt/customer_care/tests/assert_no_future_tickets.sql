-- No ticket can be created in the future (clock-skew guard, 10 min tolerance like ingestion).
select ticket_id, created_at
from {{ ref('fact_tickets') }}
where created_at > now() + interval '10 minutes'
