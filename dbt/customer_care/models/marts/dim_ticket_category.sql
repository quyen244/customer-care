select distinct
    category || '/' || coalesce(subcategory, 'unspecified')          as category_key,
    category,
    coalesce(subcategory, 'unspecified')                              as subcategory,
    initcap(replace(category, '_', ' '))                              as category_name,
    initcap(replace(coalesce(subcategory, 'unspecified'), '_', ' '))  as subcategory_name
from {{ ref('stg_ticketing__tickets') }}
where category is not null

union

select 'unknown/unspecified', 'unknown', 'unspecified', 'Unknown', 'Unspecified'
