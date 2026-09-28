-- fact_sla must cover every ticket; a gap means the incremental predicate dropped rows.
select t.ticket_id
from {{ ref('fact_tickets') }} t
left join {{ ref('fact_sla') }} s using (ticket_id)
where s.ticket_id is null
