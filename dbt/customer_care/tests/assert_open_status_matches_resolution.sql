-- Closed/resolved tickets need a resolved_at; open tickets must not have one (reopen clears it).
select ticket_id, status, is_open, resolved_at
from {{ ref('fact_tickets') }}
where (not is_open and resolved_at is null)
   or (is_open and resolved_at is not null)
