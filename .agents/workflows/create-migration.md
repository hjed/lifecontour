---
description: How to create and name alembic database migrations
---

# Creating Database Migrations

When creating new database migrations using Alembic, you must follow the project's sequential naming convention.

1. Generate the migration using Alembic:
   `cd backend && uv run alembic revision -m "your description here"`
   or
   `cd backend && uv run alembic revision --autogenerate -m "your description here"`

2. Find the newly generated migration file in `backend/app/migrations/versions/`. It will initially have a hash-based name like `285cd30b6c39_your_description_here.py`.

3. Look at the other files in `backend/app/migrations/versions/` to find the highest sequence number (e.g., `0028_...`).

4. Rename the newly generated file to use the next sequence number, zero-padded to 4 digits:
   `git mv backend/app/migrations/versions/285cd30b6c39_your_description_here.py backend/app/migrations/versions/0029_your_description_here.py`

5. Open the renamed file and update the `revision` variable to match the new sequence number string:
   Change `revision: str = '285cd30b6c39'` to `revision: str = '0029'`

6. If you are creating multiple migrations at once, ensure you also update the `down_revision` of the subsequent migrations to point to the new sequence number of the previous migration.