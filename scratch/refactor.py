import re
import os

def refactor_file(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        content = f.read()

    def replace_signature(match):
        spaces = match.group(1)
        type_hint = match.group(2)
        # e.g. type_hint is `CanyoningDataRepository` or `FromDishka[CanyoningDataRepository]`
        new_type_hint = type_hint.replace("CanyoningDataRepository", "CavingDataRepository")
        return f"{spaces}canyoning_data_repo: {type_hint},{spaces}caving_data_repo: {new_type_hint},"

    # 1. Inject in function signature with types (both standard and FromDishka)
    content = re.sub(
        r"(\n\s+)canyoning_data_repo:\s+((?:FromDishka\[)?CanyoningDataRepository(?:\])?),",
        replace_signature,
        content
    )

    # 2. Inject in kwargs
    content = re.sub(
        r"(\n\s+)canyoning_data_repo=canyoning_data_repo,",
        r"\1canyoning_data_repo=canyoning_data_repo,\1caving_data_repo=caving_data_repo,",
        content
    )

    # 3. Inject in positional args
    content = re.sub(
        r"(\n\s+)canyoning_data_repo,",
        r"\1canyoning_data_repo,\1caving_data_repo,",
        content
    )

    with open(filepath, "w") as f:
        f.write(content)

for root, _, files in os.walk("app/api"):
    for file in files:
        if file == "controllers.py":
            refactor_file(os.path.join(root, file))

def add_import(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        content = f.read()

    if "CavingDataRepository" not in content and "CanyoningDataRepository" in content:
        content = re.sub(
            r"(\n\s+)CanyoningDataRepository,",
            r"\1CanyoningDataRepository,\1CavingDataRepository,",
            content
        )
        with open(filepath, "w") as f:
            f.write(content)

for root, _, files in os.walk("app/api"):
    for file in files:
        if file == "controllers.py":
            add_import(os.path.join(root, file))
