import re

with open("backend/app/api/journals/controllers.py", "r") as f:
    content = f.read()

# 1. Import CavingDataRepository
content = re.sub(
    r"    CanyoningDataRepository,\n",
    r"    CanyoningDataRepository,\n    CavingDataRepository,\n",
    content
)

# 2. Add caving_data_repo to function signatures
# Find where canyoning_data_repo: CanyoningDataRepository is defined
content = re.sub(
    r"(    canyoning_data_repo: (FromDishka\[)?CanyoningDataRepository(\])?( \| None = None)?,)\n",
    r"\1\n    caving_data_repo: \2CavingDataRepository\3\4,\n",
    content
)

# 3. Add caving_data_repo=caving_data_repo to function calls
content = re.sub(
    r"(        canyoning_data_repo=canyoning_data_repo,)\n",
    r"\1\n        caving_data_repo=caving_data_repo,\n",
    content
)

with open("backend/app/api/journals/controllers.py", "w") as f:
    f.write(content)
