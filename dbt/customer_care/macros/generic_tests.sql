{% test non_negative(model, column_name) %}
    select {{ column_name }} from {{ model }} where {{ column_name }} < 0
{% endtest %}

{% test pct_between_0_and_100(model, column_name) %}
    select {{ column_name }} from {{ model }} where {{ column_name }} < 0 or {{ column_name }} > 100
{% endtest %}

{% test unique_combination_of_columns(model, columns) %}
    select {{ columns | join(', ') }}, count(*) as n
    from {{ model }}
    group by {{ columns | join(', ') }}
    having count(*) > 1
{% endtest %}
