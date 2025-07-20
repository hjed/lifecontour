# E2E Test Migration Guide

This guide explains how to migrate existing Playwright tests from the conditional logic pattern to the advanced fixture-based testing system.

## Overview

The advanced fixture-based testing system eliminates conditional logic in tests by providing deterministic test scenarios through comprehensive Playwright fixtures. This system includes real OAuth authentication, advanced data management, and performance optimizations that make tests more reliable, faster, and significantly easier to understand and maintain.

> 📚 **Complete Documentation**: See [`FIXTURE_SYSTEM_GUIDE.md`](./FIXTURE_SYSTEM_GUIDE.md) for comprehensive documentation of all available fixtures, data factories, and best practices.

## Key Changes

### 1. Import Changes

**Old:**

```typescript
import { test, expect } from '@playwright/test';
import { createTestHelpers } from './utils/test-helpers';
```

**New:**

```typescript
import { test, expect } from './fixtures';
// test-helpers are still available but used internally by fixtures
```

### 2. Authentication Patterns

**Old Pattern (Conditional Logic):**

```typescript
test('should handle protected page access', async ({ page }) => {
  await page.goto('/contacts');

  const { auth } = createTestHelpers(page);
  const result = await auth.handleProtectedPageAccess();

  if (result === 'redirected') {
    // Test unauthenticated behavior
    await expect(page.locator('h1')).toContainText('Welcome Back');
    // ... more unauthenticated tests
  } else {
    // Test authenticated behavior
    await expect(page.locator('h1')).toContainText('Contacts');
    // ... more authenticated tests
  }
});
```

**New Pattern (Separate Fixtures):**

```typescript
test('unauthenticated user is redirected to login', async ({
  unauthenticatedPage,
}) => {
  await unauthenticatedPage.goto('/contacts');
  await expect(unauthenticatedPage.locator('h1')).toContainText('Welcome Back');
  // ... more unauthenticated tests
});

test('authenticated user sees contacts page', async ({ authenticatedPage }) => {
  await authenticatedPage.goto('/contacts');
  await expect(authenticatedPage.locator('h1')).toContainText('Contacts');
  // ... more authenticated tests
});
```

### 3. Data Setup Patterns

**Old Pattern (Manual Setup):**

```typescript
test('should display contacts', async ({ page }) => {
  const { testData } = createTestHelpers(page);

  // Manual authentication check
  await testData.setupAuthenticatedUser();

  // Manual data setup with cleanup tracking
  const contactId = await testData.createTestContact('John', 'Doe');

  try {
    await page.goto('/contacts');
    await expect(page.locator('[data-testid="contact-list"]')).toContainText(
      'John Doe'
    );
  } finally {
    // Manual cleanup
    await testData.deleteTestContact(contactId);
  }
});
```

**New Pattern (Fixtures Handle Everything):**

```typescript
test('should display contacts', async ({ contactsWithData }) => {
  const { page, contacts } = contactsWithData;

  await page.goto('/contacts');

  // Contacts are guaranteed to exist and will be cleaned up automatically
  for (const contact of contacts) {
    await expect(
      page.locator(`[data-testid="contact-${contact.id}"]`)
    ).toBeVisible();
  }
});
```

## Available Fixtures

### Authentication Fixtures

- `authenticatedPage`: Page with real OAuth authentication (worker-scoped for performance)
- `unauthenticatedPage`: Page with no authentication (clean state)

### Basic Data Fixtures

- `contactsWithData`: Page with pre-created test contacts (2 contacts)
- `emptyContactsPage`: Page with no contacts (authenticated)
- `contactsWithTags`: Page with contacts that have tags assigned

### Advanced Dataset Fixtures

- `smallDataSet`: 5 contacts, 3 tags - perfect for quick smoke tests
- `mediumDataSet`: 20 contacts, 8 tags - comprehensive feature testing
- `largeDataSet`: 100 contacts, 15 tags - performance testing
- `searchTestData`: Optimized contacts for search functionality testing
- `favouritesTestData`: Mix of favourite/regular contacts for filtering tests
- `taggedTestData`: Hierarchical tags and complex tagging scenarios
- `performanceTestData`: 500 contacts, 50 tags - stress testing

### Specialized Fixtures

- `contactsWithoutTags`: Guaranteed untagged contacts
- `favouriteContacts`: Only favourite contacts
- `regularContacts`: Only non-favourite contacts

### Utility Fixtures

- `testCleanup`: Function to register cleanup tasks
- `dataFactory`: Access to ContactFactory, TagFactory, and DataSetFactory for custom data generation

## Advanced Patterns

### Dataset-Specific Testing

```typescript
// Use specific datasets for different test scenarios
test('search functionality with optimized data', async ({ searchTestData }) => {
  const { page, contacts, tags } = searchTestData;

  // Guaranteed: specific search test contacts exist
  const johnContact = contacts.find(c => c.lastName === 'SearchTest');
  expect(johnContact).toBeDefined();

  await page.goto('/contacts');
  await page.locator('[data-testid="search-input"]').fill('SearchTest');
  await expect(
    page.locator(`[data-testid="contact-${johnContact!.id}"]`)
  ).toBeVisible();
});

test('performance with large dataset', async ({ largeDataSet }) => {
  const { page, contacts, tags } = largeDataSet;

  // Guaranteed: 100 contacts, 15 tags for performance testing
  expect(contacts).toHaveLength(100);
  expect(tags).toHaveLength(15);

  await page.goto('/contacts');

  const startTime = Date.now();
  await page.waitForLoadState('networkidle');
  const loadTime = Date.now() - startTime;

  expect(loadTime).toBeLessThan(5000); // Performance assertion
});
```

### Custom Data Generation

```typescript
// Use data factories for custom scenarios
test('custom scenario with data factories', async ({
  authenticatedPage,
  dataFactory,
  testCleanup,
}) => {
  // Generate custom test data
  const customContacts = dataFactory.contacts.createMany(3, {
    firstName: 'CustomTest',
    isFavourite: true,
  });

  const customTags = dataFactory.tags.createWithPrefix('TestTag', 2);
  const searchDataset = dataFactory.datasets.createSearchTestData();

  // Use generated data for specific test scenario
  expect(customContacts).toHaveLength(3);
  expect(customTags).toHaveLength(2);
  expect(searchDataset.contacts).toHaveLength(4);
});
```

## Migration Steps

### Step 1: Identify Test Patterns

Look for these patterns in existing tests:

1. **Conditional Authentication Logic:**
   - `auth.handleProtectedPageAccess()`
   - `if (result === 'redirected')`
   - `navigateToPageWithAuth()`

2. **Manual Data Setup:**
   - `testData.createTestContact()`
   - `testData.setupAuthenticatedUser()`
   - Manual cleanup in `finally` blocks

3. **Mixed Scenarios:**
   - Tests that handle both authenticated and unauthenticated states
   - Tests that create data conditionally

### Step 2: Split Mixed Tests

**Before:**

```typescript
test('contact page behavior', async ({ page }) => {
  const result = await auth.handleProtectedPageAccess();

  if (result === 'redirected') {
    // Test A: Unauthenticated behavior
  } else {
    // Test B: Authenticated behavior
  }
});
```

**After:**

```typescript
test('unauthenticated user redirected from contact page', async ({
  unauthenticatedPage,
}) => {
  // Test A: Unauthenticated behavior
});

test('authenticated user sees contact page', async ({ authenticatedPage }) => {
  // Test B: Authenticated behavior
});
```

### Step 3: Replace Data Setup

**Before:**

```typescript
test('contact operations', async ({ page }) => {
  await testData.setupAuthenticatedUser();
  const contactId = await testData.createTestContact('John', 'Doe');

  try {
    // Test logic
  } finally {
    await testData.deleteTestContact(contactId);
  }
});
```

**After:**

```typescript
test('contact operations', async ({ contactsWithData }) => {
  const { page, contacts } = contactsWithData;
  // Test logic - contacts exist and cleanup is automatic
});
```

### Step 4: Update Assertions

**Before:**

```typescript
// Conditional assertions based on auth state
if (result === 'accessed') {
  await expect(page.locator('h1')).toContainText('Contacts');
}
```

**After:**

```typescript
// Direct assertions - state is guaranteed by fixture
await expect(page.locator('h1')).toContainText('Contacts');
```

## Example Migrations

### Example 1: Login Page Test

**Before:**

```typescript
test('login page functionality', async ({ page }) => {
  await page.goto('/auth/login');

  const { oauth } = createTestHelpers(page);
  const hasButtons = await oauth.handleOAuthButtons();

  if (hasButtons) {
    await expect(
      page.locator('button:has-text("Continue with")')
    ).toBeVisible();
  } else {
    console.log('OAuth not configured, skipping button test');
  }
});
```

**After:**

```typescript
test('login page shows OAuth buttons', async ({ unauthenticatedPage }) => {
  await unauthenticatedPage.goto('/auth/login');
  await expect(
    unauthenticatedPage.locator('button:has-text("Continue with")')
  ).toBeVisible();
});
```

### Example 2: Contact List Test

**Before:**

```typescript
test('contact list display', async ({ page }) => {
  const { contacts, auth } = createTestHelpers(page);

  const authResult = await contacts.navigateToPageWithAuth('/contacts');

  if (authResult === 'accessed') {
    // Test contact list functionality
    const hasContacts = await contacts.hasAnyContacts();
    if (hasContacts) {
      await expect(page.locator('[data-testid="contact-list"]')).toBeVisible();
    } else {
      await expect(page.locator('[data-testid="empty-state"]')).toBeVisible();
    }
  }
});
```

**After:**

```typescript
test('contact list shows contacts when data exists', async ({
  contactsWithData,
}) => {
  const { page } = contactsWithData;
  await page.goto('/contacts');
  await expect(page.locator('[data-testid="contact-list"]')).toBeVisible();
});

test('contact list shows empty state when no data', async ({
  emptyContactsPage,
}) => {
  await emptyContactsPage.goto('/contacts');
  await expect(
    emptyContactsPage.locator('[data-testid="empty-state"]')
  ).toBeVisible();
});
```

## Benefits of Migration

### Core Benefits

1. **Deterministic Tests**: Each test knows exactly what state it's starting with
2. **Real OAuth Authentication**: Authentic OAuth flows with Hydra provider
3. **Worker-Scoped Performance**: Authentication happens once per worker, not per test
4. **Cleaner Code**: No conditional logic cluttering test assertions
5. **Better Debugging**: Failed tests have clear, predictable state
6. **Automatic Cleanup**: No manual cleanup code needed with dependency tracking
7. **Parallel Execution**: Tests can run in parallel without interfering with each other

### Advanced Benefits

8. **Scalable Testing**: From 5 contacts (smoke tests) to 500 contacts (performance tests)
9. **Specialized Scenarios**: Purpose-built fixtures for search, favourites, tagging, etc.
10. **Data Factory System**: Generate custom test data with realistic patterns
11. **Intelligent Fallbacks**: Tests continue even with API failures using mock data
12. **Zero Test Pollution**: Complete isolation between tests with automatic cleanup
13. **Performance Optimized**: Bulk operations and efficient data management
14. **Comprehensive Documentation**: Complete guides, examples, and best practices

## Common Pitfalls

1. **Don't mix fixtures**: Use either `authenticatedPage` OR `unauthenticatedPage`, not both
2. **Don't create data manually**: Use data fixtures instead of manual API calls
3. **Don't skip cleanup**: Always use fixtures that handle cleanup automatically
4. **Don't use conditional logic**: Split tests instead of using if/else statements

## Testing the Migration

After migrating tests, verify:

1. **All tests pass consistently**: Run tests multiple times to ensure deterministic behavior
2. **No test pollution**: Tests don't affect each other when run in parallel
3. **Proper cleanup**: No leftover test data after test runs
4. **Performance improvement**: Tests should run faster due to worker-scoped auth

## Next Steps

1. Start with simple authentication tests
2. Migrate data-dependent tests to use fixtures
3. Remove old conditional logic patterns
4. Update test documentation and examples
5. Train team on new patterns
