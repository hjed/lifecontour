import glob
import re

files = glob.glob("tests/integration/journal/test_*_data_repository_integration.py")
for f in files:
    with open(f) as file:
        content = file.read()

    # In test_route fixture: Route(user_id="test-user-123", ...)
    content = content.replace('user_id="test-user-123"', "journal_id=999")

    # Ensure any stray assert .route_id cases missing from regex are gone
    content = re.sub(r"[ \t]*assert [^\n]*\.route_id[^\n]*\n", "", content)

    with open(f, "w") as file:
        file.write(content)
