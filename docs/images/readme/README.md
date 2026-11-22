# README screenshots

The images in this folder are the screenshots in the root README's Features section. They are
generated, not hand-made: `frontend/tests/screenshots/readme.screenshots.ts` seeds a small,
entirely fictional dataset on the local e2e stack and captures each screen, alternating light and
dark mode.

## Regenerating

From `frontend/`, with the workspace environment exported:

```bash
eval "$(python3 ../scripts/workspace_env.py export)"
pnpm screenshots:readme
```

Playwright starts the e2e Docker stack and frontend just as `pnpm test:e2e` does (see the
`running-e2e-tests` skill). The script **clears every contact and journal** before seeding, so it
must only ever run against the e2e test backend, never a real instance.

Review the new images before committing them: check for loading skeletons and empty states, and
that only the fictional data appears.
