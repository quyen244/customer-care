-- Lifecycle timestamps must be monotonic: created <= first response, created <= resolved <= closed.
select ticket_id, created_at, first_response_at, resolved_at, closed_at
from {{ ref('fact_tickets') }}
where first_response_at < created_at
   or resolved_at < created_at
   or closed_at < resolved_at
