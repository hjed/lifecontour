from datetime import datetime

logbook_types = {"BUSHWALKING", "CANYONING"}
user_id = "test_user"
start_date = None
end_date = None

table_map = {
    "OUTDOOR_ACTIVITY": "journal_outdoor_activity_data",
    "BUSHWALKING": "journal_bushwalking_data",
    "CANYONING": "journal_canyoning_data",
    "CAVING": "journal_caving_data",
    "CLIMBING": "journal_climbing_data",
    "KAYAKING": "journal_kayaking_data",
    "CROSS_COUNTRY_SKIING": "journal_skiing_data",
    "CANOEING": "journal_canoeing_data",
    "SNORKELLING": "journal_snorkelling_data",
    "DIVING": "journal_diving_data",
    "DOWNHILL_SKIING": "journal_downhill_skiing_data",
    "ABSEILING_TRIP": "journal_abseiling_data",
    "OUTDOOR_PLANNING": "journal_outdoor_planning_data",
    "OUTDOOR_TRAINING": "journal_outdoor_training_data",
    "GEAR_MAINTENANCE": "journal_gear_maintenance_data",
    "EVENT": "journal_calendar_info",
}

joins = []
where_conditions = []
alias_idx = 0
for t in logbook_types:
    if t in table_map:
        alias = f"t{alias_idx}"
        table = table_map[t]
        joins.append(f"LEFT JOIN {table} {alias} ON j.id = {alias}.journal_id")
        where_conditions.append(f"{alias}.journal_id IS NOT NULL")
        alias_idx += 1

date_filters = ""
if start_date:
    date_filters += " AND j.event_date_range_start >= :start_date"
if end_date:
    date_filters += " AND j.event_date_range_start <= :end_date"

cte_sql = f"""
    WITH RECURSIVE
    matching_journals AS (
        SELECT j.id, j.parent_id
        FROM journals j
        {' '.join(joins)}
        WHERE j.user_id = :user_id
        AND ( {' OR '.join(where_conditions)} )
        {date_filters}
    ),
    ancestors AS (
        SELECT id, parent_id FROM matching_journals
        UNION
        SELECT j.id, j.parent_id
        FROM journals j
        JOIN ancestors a ON j.id = a.parent_id
    ),
    descendants AS (
        SELECT id, parent_id FROM matching_journals
        UNION
        SELECT j.id, j.parent_id
        FROM journals j
        JOIN descendants d ON j.parent_id = d.id
    ),
    final_ids AS (
        SELECT id FROM ancestors
        UNION
        SELECT id FROM descendants
    )
    SELECT j.id, j.title, j.content, j.event_date_range_start, j.event_date_range_end, j.parent_id
    FROM journals j
    JOIN final_ids f ON j.id = f.id
"""
print(cte_sql)
