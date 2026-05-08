---
name: preparing-for-commit
description: review this before making any commit
---

**Under no circumstances commit with --no-verify, the precommit hooks are critical and CI will imediately fail if they are not run.**

When you are preparing for a commit please consider the following:

1. Refer back the implementation plan and ensure we've implemented what we expected to. Also check any iteration or task documents that we were referencing. If these are incorrect consider if we need to make changes before commiting.

2. Check that you have recently run *ALL* unit tests for the type of code you've touched (backend, frontend, core_shared, etc). If not, run them now. If there are failures, fix them before commiting. Ensure your fixes align with your implementation plan and any specification you were provided.

3. If you have made backend changes or changes to core_shared run the backend integration tests.

4. If you have made core_shared or worker changes make sure you've run the relevant worker integration tests.

5. If you've made frontend tests ensure you've at least run the e2e tests related to your changes. If you've made significant changes consider running all of them.

6. Remove any scratch or temporary files you've created as part of the task. These are not wanted in the repository.

For each of these steps the recent run should have been after all file changes were done.

Only once you've done all of the above should you consider making a commit. Reapt the process if you make changes

DO NOT make commit names such as "fix pr comments", the commit message should reflect what the commit actually changes. If you are updating a previous change that hasn't been merged yet its often better to amend the previous commit.