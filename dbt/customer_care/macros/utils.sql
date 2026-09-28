{# Wall-clock "now" used for time-dependent SLA logic; overridable in unit tests. #}
{% macro current_ts() -%}
    now()
{%- endmacro %}

{% macro date_key(ts) -%}
    to_char(({{ ts }}) at time zone 'UTC', 'YYYYMMDD')::integer
{%- endmacro %}

{% macro minutes_between(start_ts, end_ts) -%}
    round((extract(epoch from ({{ end_ts }}) - ({{ start_ts }})) / 60.0)::numeric, 2)
{%- endmacro %}
