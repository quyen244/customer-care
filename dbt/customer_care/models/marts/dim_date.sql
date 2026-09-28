with days as (
    select generate_series(date '2023-01-01', (current_date + interval '365 days')::date, interval '1 day')::date as d
)
select
    to_char(d, 'YYYYMMDD')::integer            as date_key,
    d                                          as date,
    extract(isodow from d)::smallint           as iso_day_of_week,
    trim(to_char(d, 'Day'))                    as day_name,
    extract(isodow from d) in (6, 7)           as is_weekend,
    date_trunc('week', d)::date                as week_start_date,
    extract(week from d)::smallint             as iso_week,
    extract(month from d)::smallint            as month,
    trim(to_char(d, 'Month'))                  as month_name,
    to_char(d, 'YYYY-MM')                      as year_month,
    extract(quarter from d)::smallint          as quarter,
    extract(year from d)::smallint             as year
from days
