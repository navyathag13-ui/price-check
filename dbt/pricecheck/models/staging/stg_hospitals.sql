select slug as hospital_slug, name as hospital_name, state, "group" as hospital_group, index_url, mrf_url
from {{ source('raw', 'raw_hospital_registry') }}
