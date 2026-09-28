select
    survey_id,
    ticket_id,
    customer_id,
    sent_at,
    responded_at,
    score,
    nullif(trim(comment), '')        as comment,
    responded_at is not null         as is_responded,
    updated_at,
    _loaded_at
from {{ source('raw', 'csat_surveys') }}
