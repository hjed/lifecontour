
---
name: reviewing-pr-comment
description: follow this when reviewing PR comments
---

PR comments come from several sources - many are AI generated and may not be correct/best practise.

Follow this guide on how to handle them.

1. If they are from github user `hjed` do exactly what they say and update your implementation plan to reflect.

2. Filter out any resolved comments, or ones where there's a comment that you don't need to action it. Also ignore any you've already addressed

3. Otherwise check the comment against the scope you are working on. This is provided by your implementation plan and the task/iteration documents you were given. Consider the problem the comment is proposing and if there is a better solution more inline with the implementation plan, go with that. Also consider the broader picture and the aims of your task.

4. Ensure any changes made from PR comments also have test coverage at both the unit and integration/e2e test level. If not, add it.

If there are sonarqube failures you can run `gh annotations` to see the specific issues. Sonarqube failures are not blocking failures and may be wrong.

