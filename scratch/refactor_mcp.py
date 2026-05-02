import re

filepath = "backend/app/mcp/domains/journals/tools.py"
with open(filepath, "r") as f:
    content = f.read()

# 1. _build_caving_data
caving_build_func = """
def _build_caving_data(caving_data: Any) -> dict[str, Any]:
    \"\"\"Build caving data dictionary.\"\"\"
    return {
        "is_vertical": caving_data.is_vertical,
        "is_horizontal": caving_data.is_horizontal,
        "template_id": str(caving_data.template_id) if caving_data.template_id else None,
    }
"""

content = content.replace(
    'def _build_canyoning_data(canyoning_data: Any) -> dict[str, Any]:',
    caving_build_func + '\n\ndef _build_canyoning_data(canyoning_data: Any) -> dict[str, Any]:'
)

# 2. _update_caving_data
caving_update_func = """
async def _update_caving_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    caving_data_repo: SqlCavingDataRepository,
) -> None:
    existing_caving = await caving_data_repo.find_by_journal_id(journal_id)
    if existing_caving:
        cav_updates: dict[str, Any] = {}
        for field in [
            "is_vertical",
            "is_horizontal",
            "template_id",
        ]:
            if field in type_data_dict:
                cav_updates[field] = type_data_dict[field]
        validated_caving = dataclasses.replace(existing_caving, **cav_updates)
        await caving_data_repo.save(validated_caving)
"""

content = content.replace(
    'async def _update_canyoning_data(',
    caving_update_func + '\n\nasync def _update_canyoning_data('
)

# 3. Add to _fetch_journal_types_and_data inside the function body
fetch_caving_logic = """
    caving_data = await caving_data_repo.find_by_journal_id(journal_id)
    if caving_data:
        types.append(JournalType.CAVING.value)
        type_data[JournalType.CAVING.value] = _build_caving_data(caving_data)
"""

content = content.replace(
    '    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)',
    fetch_caving_logic + '\n    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)'
)

# 4. Add to _create_type_specific_data inside the function body
create_caving_logic = """
        elif type_name == JournalType.CAVING.value:
            await caving_data_repo.save(CavingData(journal_id=journal_id))
"""

content = content.replace(
    '        elif type_name == JournalType.CANYONING.value:\n            await canyoning_data_repo.save(CanyoningData(journal_id=journal_id))',
    create_caving_logic + '        elif type_name == JournalType.CANYONING.value:\n            await canyoning_data_repo.save(CanyoningData(journal_id=journal_id))'
)

# 5. Add to _update_type_specific_data inside the function body
update_caving_logic = """
    elif journal_type == JournalType.CAVING:
        await _update_caving_data(journal_id, type_data_dict, caving_data_repo)
"""

content = content.replace(
    '    elif journal_type == JournalType.CANYONING:\n        await _update_canyoning_data(journal_id, type_data_dict, canyoning_data_repo)',
    update_caving_logic + '    elif journal_type == JournalType.CANYONING:\n        await _update_canyoning_data(journal_id, type_data_dict, canyoning_data_repo)'
)

# 6. Add "caving_data_repo: SqlCavingDataRepository," to the signatures.
content = re.sub(
    r"(\s+canyoning_data_repo:\s+SqlCanyoningDataRepository,)",
    r"\1\n    caving_data_repo: SqlCavingDataRepository,",
    content
)

# 7. Add caving_data_repo to calls.
content = re.sub(
    r"(\s+repos\.canyoning_data_repo,)",
    r"\1\n        repos.caving_data_repo,",
    content
)

# 8. Add caving_data_repo to docstrings
content = re.sub(
    r"(\s+canyoning_data_repo: Repository for canyoning data)",
    r"\1\n        caving_data_repo: Repository for caving data",
    content
)
content = re.sub(
    r"(\s+canyoning_data_repo: Canyoning data repository)",
    r"\1\n        caving_data_repo: Caving data repository",
    content
)

# Add JournalType.CAVING to precedence if it exists
content = content.replace(
    "JournalType.CANYONING,",
    "JournalType.CANYONING,\n    JournalType.CAVING,"
)

# 9. Add imports
content = content.replace(
    "    CanyoningData,",
    "    CanyoningData,\n    CavingData,"
)
content = content.replace(
    "from app.core.journal.adapters.sql.canyoning_data_repository import (\n    SqlCanyoningDataRepository,\n)",
    "from app.core.journal.adapters.sql.canyoning_data_repository import (\n    SqlCanyoningDataRepository,\n)\nfrom app.core.journal.adapters.sql.caving_data_repository import (\n    SqlCavingDataRepository,\n)"
)

# 10. Add to _JournalToolRepositories fields (without trailing comma!)
content = content.replace(
    "    canyoning_data_repo: SqlCanyoningDataRepository\n",
    "    canyoning_data_repo: SqlCanyoningDataRepository\n    caving_data_repo: SqlCavingDataRepository\n"
)

# 11. Add to _create_journal_tool_repositories instantiation
content = content.replace(
    "        canyoning_data_repo=SqlCanyoningDataRepository(db_connection),",
    "        canyoning_data_repo=SqlCanyoningDataRepository(db_connection),\n        caving_data_repo=SqlCavingDataRepository(db_connection),"
)

with open(filepath, "w") as f:
    f.write(content)
