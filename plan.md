## Execution Plan for Phase 2

1. **Frontend Types**: Update `frontend/src/types/integrations.ts` to include registry schemas (`IntegrationData`, `IntegrationAttributes`, `IntegrationListResponse`, etc.). Add types for `/api/health/dead-letters`.
2. **Frontend APIs**: Add React Query hooks `useIntegrations` and `useDeadLetters` in `frontend/src/lib/api/integrations.ts`.
3. **Components**:
   - Create generic `IntegrationPanel` in `frontend/src/components/integrations/IntegrationPanel.tsx`.
   - Create generic `ConnectionControls` in `frontend/src/components/integrations/ConnectionControls.tsx`.
   - Create generic `SyncControls` in `frontend/src/components/integrations/SyncControls.tsx`.
   - Create `DeadLetterQueue` display in `frontend/src/components/integrations/DeadLetterQueue.tsx`.
4. **Refactor Page**: Modify `frontend/src/app/integrations/page.tsx` to dynamically render `IntegrationPanel` components based on the registry, and include the `DeadLetterQueue` below or beside health/settings.
5. **Quality checks**: Ensure `pnpm lint`, `pnpm type-check` pass. Ensure E2E tests `frontend/tests/e2e/integrations.spec.ts` pass and update selectors/logic as needed.
6. **Documentation**: Update the iteration doc task list.
