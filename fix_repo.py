import re

with open('backend/app/core/journal/adapters/sql/logbook_export_repository.py', 'r') as f:
    content = f.read()

# 1. Add json and datetime imports
if 'import json' not in content:
    content = content.replace('from typing import Any', 'import json\nfrom typing import Any')

content = content.replace('from datetime import UTC', 'from datetime import UTC, datetime')

# 2. Fix activity_types uppercase filter
content = content.replace(
    'logbook_types = [t for t in logbook_types if t in activity_types]',
    'activity_types_upper = [t.upper() for t in activity_types]\n            logbook_types = [t for t in logbook_types if t in activity_types_upper]'
)

# 3. Remove old date_filters block
old_date_filters = '''        date_filters = ""
        if start_date:
            date_filters += " AND j.start_time >= :start_date"
            query_params["start_date"] = start_date
        if end_date:
            date_filters += " AND j.end_time <= :end_date"
            query_params["end_date"] = end_date'''
content = content.replace(old_date_filters, '')

# 4. Fix correct date_filters block
old_new_date = '''        if start_date:
            date_filters += " AND j.event_date_range_start >= :start_date"
            query_params["start_date"] = start_date
        if end_date:
            date_filters += " AND j.event_date_range_end <= :end_date"
            query_params["end_date"] = end_date'''

new_new_date = '''        if start_date:
            date_filters += " AND j.event_date_range_end >= :start_date"
            dt = datetime.fromisoformat(start_date)
            query_params["start_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        if end_date:
            date_filters += " AND j.event_date_range_start <= :end_date"
            dt_end = datetime.fromisoformat(end_date)
            query_params["end_date"] = dt_end if dt_end.tzinfo else dt_end.replace(tzinfo=UTC)'''
content = content.replace(old_new_date, new_new_date)

# 5. Fix user_id scoping in CTEs
ancestors_replace = '''                SELECT j.id, j.parent_id
                FROM journals j
                JOIN ancestors a ON j.id = a.parent_id
            ),'''
ancestors_with = '''                SELECT j.id, j.parent_id
                FROM journals j
                JOIN ancestors a ON j.id = a.parent_id
                WHERE j.user_id = :user_id
            ),'''
content = content.replace(ancestors_replace, ancestors_with)

desc_replace = '''                SELECT j.id, j.parent_id
                FROM journals j
                JOIN descendants d ON j.parent_id = d.id
            ),'''
desc_with = '''                SELECT j.id, j.parent_id
                FROM journals j
                JOIN descendants d ON j.parent_id = d.id
                WHERE j.user_id = :user_id
            ),'''
content = content.replace(desc_replace, desc_with)

# 6. Fix contacts role
contacts_old = '''        contacts_sql = """
            SELECT
                r.journal_id, r.contact_id, r.role,
                TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')) as name
            FROM journal_contact_relationships r
            JOIN contacts c ON r.contact_id = c.id
            WHERE r.journal_id = ANY(:journal_ids)
        """'''
contacts_new = '''        contacts_sql = """
            SELECT
                r.journal_id, r.contact_id, r.relationship_type as role,
                TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')) as name
            FROM journal_contact_relationships r
            JOIN contacts c ON r.contact_id = c.id
            WHERE r.journal_id = ANY(:journal_ids)
            AND r.relationship_type IN ('PARTICIPANT', 'INVITEE')
        """'''
content = content.replace(contacts_old, contacts_new)

# 7. Fix AbseilPitch
pitch_old = '''        for row in result.fetchall():
            pitches_by_journal[row.journal_id].append(
                AbseilPitch(
                    id=row.id,
                    journal_id=row.journal_id,
                    pitch_number=row.pitch_number,
                    height=row.height,
                    anchor_location=row.anchor_location,
                    anchor_type=row.anchor_type,
                    did_rescue=row.did_rescue,
                    did_setup=row.did_setup,
                )
            )'''
pitch_new = '''        for row in result.fetchall():
            try:
                pitches_by_journal[row.journal_id].append(
                    AbseilPitch(
                        id=row.id,
                        journal_id=row.journal_id,
                        pitch_number=row.pitch_number,
                        height=row.height,
                        anchor_location=row.anchor_location,
                        anchor_type=row.anchor_type,
                        did_rescue=row.did_rescue,
                        did_setup=row.did_setup,
                    )
                )
            except ValueError:
                pass'''
content = content.replace(pitch_old, pitch_new)

# 8. Fix JSONB for activity_types
json_old = '''                kwargs = {
                    k: v
                    for k, v in data_dict.items()
                    if hasattr(domain_cls, k) or k in domain_cls.__annotations__
                }'''
json_new = '''                kwargs = {
                    k: (json.loads(v) if k == "activity_types" and isinstance(v, str) else v)
                    for k, v in data_dict.items()
                    if hasattr(domain_cls, k) or k in domain_cls.__annotations__
                }'''
content = content.replace(json_old, json_new)

with open('backend/app/core/journal/adapters/sql/logbook_export_repository.py', 'w') as f:
    f.write(content)

