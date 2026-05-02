import re
import os

def fix_file(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        content = f.read()

    # Find and insert caving_data_repo before climbing_data_repo in function calls
    content = re.sub(
        r"(\s+)(climbing_data_repo,?)",
        r"\1caving_data_repo,\1\2",
        content
    )

    with open(filepath, "w") as f:
        f.write(content)

fix_file("app/api/journals/controllers.py")
fix_file("app/api/contacts/controllers.py")
