import re

with open("backend/app/core/journal/adapters/sql/logbook_export_repository.py", "r") as f:
    content = f.read()

# We need to replace everything from `if not logbook_types:` to the start of `# 4. Fetch related data` (wait, actually, `# 2. Fetch all journal types` is right after we get the journal_rows).
# Since we now directly get `final_journal_rows` and `final_journal_ids`, we just execute `types_sql` using `final_journal_ids` instead of `journal_ids`. Then we skip `# 3. Filter journal rows based on criteria` entirely!

# So:
# START: `# To avoid complex CTEs right now`
# END: `# 4. Fetch related data`

start_str = "        # To avoid complex CTEs right now, let's just fetch ALL journals for the user"
end_str = "        # 4. Fetch related data for these final journal IDs"

start_idx = content.find(start_str)
end_idx = content.find(end_str)

if start_idx == -1 or end_idx == -1:
    print("Could not find blocks")
    exit(1)

new_block = """
        query_params: dict[str, Any] = {"user_id": user_id}

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

        if not where_conditions:
            return []

        date_filters = ""
        if start_date:
            date_filters += " AND j.event_date_range_start >= :start_date"
            query_params["start_date"] = start_date
        if end_date:
            date_filters += " AND j.event_date_range_start <= :end_date"
            query_params["end_date"] = end_date

        cte_sql = f\"\"\"
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
        \"\"\"

        result = await self.connection.execute(text(cte_sql), query_params)
        final_journal_rows = result.fetchall()

        if not final_journal_rows:
            return []

        final_journal_ids = [row.id for row in final_journal_rows]

        # 2. Fetch all journal types for the final journal ids
        types_sql = \"\"\"
            SELECT j.id as journal_id,
                CASE WHEN jci.journal_id IS NOT NULL THEN 'EVENT' END as event_type,
                CASE WHEN jmd.journal_id IS NOT NULL THEN 'MOOD_RATING' END as mood_type,
                CASE WHEN jpd.journal_id IS NOT NULL THEN 'PLAN' END as plan_type,
                CASE WHEN jtd.journal_id IS NOT NULL THEN 'TRAVEL' END as travel_type,
                CASE WHEN jpad.journal_id IS NOT NULL THEN 'PHOTO_ALBUM' END as photo_type,
                CASE WHEN jfd.journal_id IS NOT NULL THEN 'FITNESS' END as fitness_type,
                CASE WHEN joad.journal_id IS NOT NULL THEN 'OUTDOOR_ACTIVITY' END as outdoor_activity_type,
                CASE WHEN jbwd.journal_id IS NOT NULL THEN 'BUSHWALKING' END as bushwalking_type,
                CASE WHEN jjd.journal_id IS NOT NULL THEN 'JOGGING' END as jogging_type,
                CASE WHEN jabd.journal_id IS NOT NULL THEN 'ABSEILING_TRIP' END as abseiling_type,
                CASE WHEN jcyd.journal_id IS NOT NULL THEN 'CANYONING' END as canyoning_type,
                CASE WHEN jcld.journal_id IS NOT NULL THEN 'CLIMBING' END as climbing_type,
                CASE WHEN jkyd.journal_id IS NOT NULL THEN 'KAYAKING' END as kayaking_type,
                CASE WHEN jskid.journal_id IS NOT NULL THEN 'CROSS_COUNTRY_SKIING' END as skiing_type,
                CASE WHEN jcvd.journal_id IS NOT NULL THEN 'CAVING' END as caving_type,
                CASE WHEN jcnd.journal_id IS NOT NULL THEN 'CANOEING' END as canoeing_type,
                CASE WHEN jsnkd.journal_id IS NOT NULL THEN 'SNORKELLING' END as snorkelling_type,
                CASE WHEN jdivd.journal_id IS NOT NULL THEN 'DIVING' END as diving_type,
                CASE WHEN jdsd.journal_id IS NOT NULL THEN 'DOWNHILL_SKIING' END as downhill_skiing_type,
                CASE WHEN jopd.journal_id IS NOT NULL THEN 'OUTDOOR_PLANNING' END as outdoor_planning_type,
                CASE WHEN jgmd.journal_id IS NOT NULL THEN 'GEAR_MAINTENANCE' END as gear_maintenance_type
            FROM journals j
            LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id
            LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id
            LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id
            LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id
            LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id
            LEFT JOIN journal_fitness_data jfd ON j.id = jfd.journal_id
            LEFT JOIN journal_outdoor_activity_data joad ON j.id = joad.journal_id
            LEFT JOIN journal_bushwalking_data jbwd ON j.id = jbwd.journal_id
            LEFT JOIN journal_jogging_data jjd ON j.id = jjd.journal_id
            LEFT JOIN journal_abseiling_data jabd ON j.id = jabd.journal_id
            LEFT JOIN journal_canyoning_data jcyd ON j.id = jcyd.journal_id
            LEFT JOIN journal_climbing_data jcld ON j.id = jcld.journal_id
            LEFT JOIN journal_kayaking_data jkyd ON j.id = jkyd.journal_id
            LEFT JOIN journal_skiing_data jskid ON j.id = jskid.journal_id
            LEFT JOIN journal_caving_data jcvd ON j.id = jcvd.journal_id
            LEFT JOIN journal_canoeing_data jcnd ON j.id = jcnd.journal_id
            LEFT JOIN journal_snorkelling_data jsnkd ON j.id = jsnkd.journal_id
            LEFT JOIN journal_diving_data jdivd ON j.id = jdivd.journal_id
            LEFT JOIN journal_downhill_skiing_data jdsd ON j.id = jdsd.journal_id
            LEFT JOIN journal_outdoor_planning_data jopd ON j.id = jopd.journal_id
            LEFT JOIN journal_gear_maintenance_data jgmd ON j.id = jgmd.journal_id
            WHERE j.id = ANY(:journal_ids)
        \"\"\"
        result = await self.connection.execute(
            text(types_sql), {"journal_ids": final_journal_ids}
        )
        types_by_journal = defaultdict(list)
        for row in result.fetchall():
            for i in range(1, len(row)):
                if row[i]:
                    types_by_journal[row.journal_id].append(row[i])

        # Determine if 'NOTE' applies to any
        for jid in final_journal_ids:
            if not types_by_journal[jid]:
                types_by_journal[jid].append("NOTE")

"""

new_content = content[:start_idx] + new_block + content[end_idx:]
with open("backend/app/core/journal/adapters/sql/logbook_export_repository.py", "w") as f:
    f.write(new_content)

print("Done")
