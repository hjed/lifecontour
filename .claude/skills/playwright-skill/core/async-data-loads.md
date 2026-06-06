# Handling React Query and Async Data Loads

> How to wait for asynchronous data fetching and cache invalidations (like React Query) in Playwright without using brittle `waitForTimeout()` sleeps or excessive `toPass()` polling loops.

When testing modern React applications that use tools like React Query, RTK Query, or SWR, the UI state is completely decoupled from the initial page load. Data is fetched asynchronously, and UI updates (like showing a list of items after a creation) happen only *after* background invalidation refetches complete.

## ❌ The Anti-Pattern: Brittle Wait Loops and Sleeps

Do not use arbitrary sleeps or aggressive `.toPass()` loops just to wait for the UI to update if the state is driven by a deterministic network request.

```typescript
// ❌ BAD: Flaky, slow, and hides the underlying network sequence
await page.getByRole('button', { name: 'Save' }).click();

await expect(async () => {
  await page.reload(); // Bruteforce refresh
  await expect(page.getByText('New Item')).toBeVisible();
}).toPass({ timeout: 15000 });
```

## ✅ The Golden Pattern: Sequential Network Assertions

When a mutation (e.g., `POST`) triggers a cache invalidation and a subsequent refetch (e.g., `GET`), **always wait for the `GET` request directly** before asserting on the updated UI.

This correctly models the exact lifecycle of React Query in the browser.

```typescript
// ✅ GOOD: Await the specific mutation and its subsequent invalidation refetch
const postPromise = page.waitForResponse(
  resp =>
    resp.url().includes('/api/items') &&
    resp.request().method() === 'POST' &&
    resp.ok()
);

await page.getByRole('button', { name: 'Save' }).click();
await postPromise; // Wait for the mutation to succeed

// Now wait for the React Query cache invalidation refetch
await page.waitForResponse(
  resp =>
    resp.url().includes('/api/items') &&
    resp.request().method() === 'GET' &&
    resp.ok()
);

// The UI will now deterministically contain the updated data
await expect(page.getByText('New Item')).toBeVisible();
```

### Why not `Promise.all` for both?

You should avoid doing `Promise.all` for both the `POST` and the `GET` alongside the click action, as it can occasionally catch an inflight `GET` request from *before* the mutation succeeded (e.g., background polling).

Waiting for the `GET` *after* the `POST` resolves ensures you are strictly catching the invalidation refetch.

## When Polling Loops *Are* Necessary

If the data you are waiting for is synchronized by an **asynchronous backend process** (e.g., a Message Queue, an Outbox Worker, or eventual consistency into a Search Index like MeiliSearch or Elasticsearch), React Query's `GET` request may return *stale* data immediately after the `POST`.

In this specific scenario, a polling loop is mandatory because there is no frontend network request that can signal when the backend index has finished updating.

```typescript
// ✅ ACCEPTABLE: Waiting for backend eventual consistency (e.g., MeiliSearch)
await page.getByRole('button', { name: 'Index Document' }).click();

// We must poll and reload until the background worker finishes indexing
await expect(async () => {
  await page.reload();
  await expect(page.getByText('Indexed Document')).toBeVisible({ timeout: 2000 });
}).toPass({ timeout: 30000 });
```

### Key Differences
- **PostgreSQL / Direct DB read**: Strict consistency. Use `waitForResponse` for the GET request.
- **Search Indexes / Async Workers**: Eventual consistency. Use `.toPass()` loops with `page.reload()`.
