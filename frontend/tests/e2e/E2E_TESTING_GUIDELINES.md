# E2E Testing Guidelines

This document outlines best practices for writing reliable, maintainable end-to-end tests using Playwright.

## Core Principles

### 1. Use Web-First Assertions (Auto-Retry)

Playwright assertions auto-retry until the condition is met or timeout. **Always prefer web-first assertions over manual checks.**

```typescript
// ✅ GOOD - Web-first assertion (auto-retries)
await expect(page.getByText('Welcome')).toBeVisible();
await expect(page.locator('.status')).toHaveText('Success');
await expect(page).toHaveURL(/\/contacts/);

// ❌ BAD - Manual assertion (no retry, prone to flakiness)
const text = await page.textContent('.status');
expect(text).toBe('Success');

const isVisible = await page.getByText('Welcome').isVisible();
expect(isVisible).toBe(true);
```

### 2. Avoid Hard-Coded Waits

Never use `waitForTimeout()` in production tests. Use proper wait conditions instead.

```typescript
// ❌ BAD - Hard-coded wait (flaky, slow)
await page.waitForTimeout(3000);
await page.click('button');

// ✅ GOOD - Wait for specific condition
await expect(page.getByRole('button', { name: 'Submit' })).toBeEnabled();
await page.getByRole('button', { name: 'Submit' }).click();

// ✅ GOOD - Wait for navigation
await Promise.all([
  page.waitForURL('**/contacts/**'),
  page.getByRole('link', { name: 'Contacts' }).click(),
]);

// ✅ GOOD - Wait for API response
const responsePromise = page.waitForResponse('/api/contacts');
await page.getByRole('button', { name: 'Load' }).click();
await responsePromise;
```

### 3. Use Resilient Locators

Prefer locators that are resilient to DOM changes.

```typescript
// ✅ GOOD - Role-based (most resilient, accessibility-focused)
page.getByRole('button', { name: 'Submit' });
page.getByRole('heading', { name: 'Contacts' });
page.getByRole('link', { name: 'Home' });

// ✅ GOOD - Test IDs (explicit, stable)
page.getByTestId('contact-card');
page.locator('[data-testid="submit-button"]');

// ✅ GOOD - Text content (human-readable)
page.getByText('Welcome');
page.getByLabel('Email');
page.getByPlaceholder('Search...');

// ⚠️ CAUTION - CSS selectors (may break with styling changes)
page.locator('.contact-card');
page.locator('#main-content');

// ❌ BAD - Complex CSS chains (fragile)
page.locator('div.container > div.row > div.col > button');
page.locator('#tsf > div:nth-child(2) > div.A8SBwf');
```

### 4. Avoid `waitForLoadState('networkidle')`

`networkidle` waits until no network requests for 500ms, which is unreliable for SPAs with polling or lazy loading.

```typescript
// ❌ BAD - networkidle is unreliable
await page.goto('/contacts');
await page.waitForLoadState('networkidle');

// ✅ GOOD - Wait for specific element that indicates page is ready
await page.goto('/contacts');
await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible();

// ✅ GOOD - Wait for data to load
await page.goto('/contacts');
await expect(page.getByTestId('contacts-list')).toBeVisible();
```

### 5. Handle Authentication Properly

Use fixtures for consistent authentication state.

```typescript
// ✅ GOOD - Use authentication fixtures
test('should display contacts', async ({ authenticatedPage }) => {
  await authenticatedPage.goto('/contacts');
  await expect(
    authenticatedPage.getByRole('heading', { name: 'Contacts' })
  ).toBeVisible();
});

test('should redirect to login', async ({ unauthenticatedPage }) => {
  await unauthenticatedPage.goto('/contacts');
  await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);
});
```

### 6. Wait for Actions to Complete

When triggering actions, wait for the expected outcome.

```typescript
// ✅ GOOD - Wait for navigation and verify result
await Promise.all([
  page.waitForURL('**/contacts/**'),
  page.getByRole('link', { name: 'Contacts' }).click(),
]);
await expect(page).toHaveURL(/\/contacts/);

// ✅ GOOD - Wait for API response after form submission
const responsePromise = page.waitForResponse('/api/contacts');
await page.getByRole('button', { name: 'Save' }).click();
const response = await responsePromise;
expect(response.ok()).toBe(true);

// ✅ GOOD - Wait for element state change
await page.getByRole('button', { name: 'Favourite' }).click();
await expect(page.getByRole('button', { name: 'Unfavorite' })).toBeVisible();
```

### 7. Use Explicit Assertions Over Conditional Logic

Avoid `if` statements that change test behavior based on state.

```typescript
// ❌ BAD - Conditional logic hides issues
const errorCount = await page.locator('.error').count();
if (errorCount > 0) {
  // Handle error
} else {
  // Proceed
}

// ✅ GOOD - Explicit assertions
await expect(page.locator('.error')).not.toBeVisible();
await expect(page.getByRole('heading', { name: 'Success' })).toBeVisible();
```

### 8. Clean Up Test Data

Always clean up test data to ensure test isolation.

```typescript
// ✅ GOOD - Use fixtures with automatic cleanup
test('should create contact', async ({ contactsWithData }) => {
  const { page, contacts } = contactsWithData;
  // Test runs with guaranteed contacts
  // Cleanup happens automatically after test
});

// ✅ GOOD - Manual cleanup when needed
test('should create tag', async ({ authenticatedPage }) => {
  const response = await authenticatedPage.request.post('/api/tags', { ... });
  const tagId = (await response.json()).data.id;

  try {
    // Test logic
    await authenticatedPage.goto(`/contacts/tags/${tagId}`);
    await expect(authenticatedPage.getByRole('heading')).toContainText('Tag');
  } finally {
    // Always clean up
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  }
});
```

## Common Patterns

### Waiting for Page Load

```typescript
// Wait for specific content that indicates page is ready
await page.goto('/contacts');
await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible();

// For pages with data loading
await page.goto('/contacts');
await expect(page.getByTestId('contacts-loaded')).toBeVisible();
// OR wait for the absence of loading indicator
await expect(page.getByTestId('loading-spinner')).not.toBeVisible();
```

### Testing Form Submission

```typescript
// Fill form and submit
await page.getByLabel('First Name').fill('John');
await page.getByLabel('Last Name').fill('Doe');
await page.getByLabel('Email').fill('john@example.com');

// Wait for submission result
await Promise.all([
  page.waitForURL('**/contacts/**'),
  page.getByRole('button', { name: 'Save' }).click(),
]);

// Verify success
await expect(page.getByText('Contact saved')).toBeVisible();
```

### Testing Navigation

```typescript
// Navigation with URL verification
await Promise.all([
  page.waitForURL('**/contacts/favourites'),
  page.getByRole('link', { name: 'Favourites' }).click(),
]);
await expect(page).toHaveURL(/\/contacts\/favourites/);
await expect(page.getByRole('heading', { name: 'Favourites' })).toBeVisible();
```

### Testing API Responses

```typescript
// Wait for specific API response
const responsePromise = page.waitForResponse(
  response =>
    response.url().includes('/api/contacts') && response.status() === 200
);
await page.getByRole('button', { name: 'Load Contacts' }).click();
const response = await responsePromise;
expect(response.ok()).toBe(true);
```

### Testing Error States

```typescript
// Verify error message appears
await page.getByRole('button', { name: 'Submit' }).click();
await expect(page.getByRole('alert')).toBeVisible();
await expect(page.getByRole('alert')).toContainText('Error');
```

### Choosing a Select Option

Radix (shadcn) `Select` options render in a portal and animate in. Under
Mobile Chrome, Playwright mis-measures them, so an option click, even a
forced one, can miss. A missed click leaves the listbox open, and while it
is open Radix marks the rest of the page `aria-hidden`, including the
trigger. A retry that looks the trigger up by role then finds nothing.
Typeahead is no safer: in the production build, a space in the label
commits whichever option has focus. Use the shared helper, which opens
the select from the keyboard, focuses the option directly and commits it
with Enter:

```typescript
import { selectRadixOption } from './utils/radix-select';

await selectRadixOption(
  page,
  page.getByRole('combobox', { name: 'Important Date Precision' }),
  'Year Only'
);
```

## Anti-Patterns to Avoid

| Anti-Pattern                      | Issue               | Solution                                      |
| --------------------------------- | ------------------- | --------------------------------------------- |
| `waitForTimeout()`                | Flaky, slow         | Use web-first assertions                      |
| `waitForLoadState('networkidle')` | Unreliable for SPAs | Wait for specific elements                    |
| Manual `isVisible()` checks       | No auto-retry       | Use `toBeVisible()` assertion                 |
| Complex CSS selectors             | Fragile             | Use role/testid locators                      |
| Conditional test logic            | Hides failures      | Use explicit assertions                       |
| No test data cleanup              | Test pollution      | Use fixtures with cleanup                     |
| Catching errors silently          | Hides real issues   | Let errors propagate                          |
| `click({ force: true })`          | Skips actionability | Fix the cause; `selectRadixOption` for Select |

## Debugging Flaky Tests

1. **Enable tracing**: Set `trace: 'on'` in playwright.config.ts
2. **Add explicit waits**: Use assertions to wait for specific conditions
3. **Check CI environment**: Verify timeouts are sufficient for CI
4. **Review test isolation**: Ensure tests don't depend on order or shared state
5. **Use retries**: Configure `retries: 2` to identify flaky vs real failures
6. **Check for race conditions**: Ensure proper sequencing of async operations

## Configuration Reference

See `playwright.config.ts` for:

- Global timeouts (`timeout`, `expect.timeout`)
- Action timeouts (`actionTimeout`, `navigationTimeout`)
- Retry configuration (`retries`, `failOnFlakyTests`)
- Trace and video settings for debugging
