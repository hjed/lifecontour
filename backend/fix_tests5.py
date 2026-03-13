import glob
import re

files = glob.glob("tests/integration/journal/test_*_data_repository_integration.py")
for f in files:
    with open(f) as file:
        content = file.read()

    # In test_journal fixture: Journal(journal_id=999, ...) -> Journal(user_id="test-user-123", ...)
    content = re.sub(
        r"journal = Journal\(\s*journal_id=999,",
        'journal = Journal(\n        user_id="test-user-123",',
        content,
    )

    with open(f, "w") as file:
        file.write(content)
