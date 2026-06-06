---
name: writing-sql
description: review this before writing or editing sql queries
---

The following strict rules apply:

1. All SQL Queries must be in a `repository` in the `core_shared` or `backend` package. Using adhoc queries in services or controllers is not allowed.
2. SQL queries should enforce the use of the user id parameter so that they only ever query the data for the user requesting it. This prevents data leakage and accidental exposure of user data.
3. If you encounter a query not in a repository file, move it to a repository file.
4. Always check the parameters you use against the relevant sql alchemy model

Remember that editing journal or contact entities must go through their relevant services to trigger events!