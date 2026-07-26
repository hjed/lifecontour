# Complete E2E Fixture System Guide

## 🎯 Overview

This guide documents the comprehensive fixture-based testing system that provides deterministic, isolated, and maintainable E2E tests. The system eliminates conditional logic, provides real OAuth authentication via Playwright's setup project + storageState pattern, and offers advanced data management capabilities.

## 🏗️ Architecture

### Core Components

1. **Authentication Fixtures** - Real OAuth flow via setup project + storageState (runs once for all tests)
2. **Data Management Fixtures** - Advanced data creation with automatic cleanup
3. **Specialized Fixtures** - Purpose-built fixtures for specific scenarios
4. **Data Factories** - Realistic test data generation
5. **Cleanup System** - Automatic resource cleanup with dependency tracking

### Key Benefits

- ✅ **No Conditional Logic** - Each test has guaranteed state
- ✅ **Real OAuth Authentication** - Authentic E2E testing with Hydra
- ✅ **Deterministic Data** - Predictable test data for reliable tests
- ✅ **Automatic Cleanup** - No test pollution or resource leaks
- ✅ **Performance Optimized** - Single OAuth flow via setup project, bulk operations
- ✅ **Scalable Architecture** - Easy to extend with new fixtures

## 🔐 Authentication Fixtures

### Setup Project + storageState Pattern

Authentication uses Playwright's recommended [setup project pattern](https://playwright.dev/docs/auth):

1. **`auth.setup.ts`** runs once before all test projects — performs the real OAuth flow against Hydra
2. Saves authenticated browser state (cookies + localStorage) to `playwright/.auth/user.json`
3. All browser projects declare `dependencies: ['setup']` and `storageState: 'playwright/.auth/user.json'`
4. Every test starts pre-authenticated — zero per-test OAuth overhead

```typescript
// Automatically authenticated page - no setup needed
// storageState from setup project provides cookies
test('should access protected page', async ({ authenticatedPage }) => {
  await authenticatedPage.goto('/contacts');
  await expect(authenticatedPage).toHaveURL(/\/contacts/);
});

// Automatically unauthenticated page - clears storageState cookies
test('should redirect to login', async ({ unauthenticatedPage }) => {
  await unauthenticatedPage.goto('/contacts');
  await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);
});
```

### Real OAuth Flow

- Uses actual Hydra OAuth provider
- Auto-accepting login/consent service for deterministic flows
- Setup project runs OAuth **once** for the entire suite (not per worker or per test)
- Saves real session cookies via Playwright's `storageState`

## 📊 Data Management Fixtures

### Basic Data Fixtures

```typescript
// Pre-populated contacts with realistic data
test('should display contacts', async ({ contactsWithData }) => {
  const { page, contacts } = contactsWithData;

  await page.goto('/contacts');
  expect(contacts).toHaveLength(2); // Guaranteed data

  // Test with known data
  await expect(
    page.locator(`[data-testid="contact-${contacts[0].id}"]`)
  ).toBeVisible();
});

// Guaranteed empty state
test('should show empty state', async ({ emptyContactsPage }) => {
  await emptyContactsPage.goto('/contacts');
  await expect(
    emptyContactsPage.locator('[data-testid="empty-state"]')
  ).toBeVisible();
});

// Contacts with tags for filtering tests
test('should filter by tags', async ({ contactsWithTags }) => {
  const { page, contacts, tags } = contactsWithTags;

  await page.goto('/contacts');

  // Test tag filtering with known tags
  for (const tagName of tags) {
    await page.locator(`[data-testid="tag-filter-${tagName}"]`).click();
    // Verify filtering works
  }
});
```

### Advanced Dataset Fixtures

```typescript
// Small dataset (5 contacts, 3 tags) - for quick smoke tests
test('smoke test with small dataset', async ({ smallDataSet }) => {
  const { page, contacts, tags } = smallDataSet;
  expect(contacts).toHaveLength(5);
  expect(tags).toHaveLength(3);
});

// Medium dataset (20 contacts, 8 tags) - for comprehensive feature testing
test('comprehensive test with medium dataset', async ({ mediumDataSet }) => {
  const { page, contacts, tags } = mediumDataSet;
  expect(contacts).toHaveLength(20);
  expect(tags).toHaveLength(8);

  // Test pagination, sorting, etc.
});

// Large dataset (100 contacts, 15 tags) - for performance testing
test('performance test with large dataset', async ({ largeDataSet }) => {
  const { page, contacts, tags } = largeDataSet;
  expect(contacts).toHaveLength(100);
  expect(tags).toHaveLength(15);

  // Test performance, loading times, etc.
});

// Search-optimized dataset - specific contacts for search testing
test('search functionality', async ({ searchTestData }) => {
  const { page, contacts, tags } = searchTestData;

  // Contains specific contacts like "John SearchTest", "Jane FindMe"
  const searchContact = contacts.find(c => c.lastName === 'SearchTest');
  expect(searchContact).toBeDefined();

  await page.goto('/contacts');
  await page.locator('[data-testid="search-input"]').fill('SearchTest');
  await expect(
    page.locator(`[data-testid="contact-${searchContact!.id}"]`)
  ).toBeVisible();
});

// Favourites-optimized dataset - mix of favourite and regular contacts
test('favourites functionality', async ({ favouritesTestData }) => {
  const { page, contacts, tags } = favouritesTestData;

  const favourites = contacts.filter(c => c.isFavourite);
  const regular = contacts.filter(c => !c.isFavourite);

  expect(favourites.length).toBeGreaterThan(0);
  expect(regular.length).toBeGreaterThan(0);

  // Test favourites filtering
});
```

### Specialized Fixtures

```typescript
// Only favourite contacts
test('favourites page', async ({ favouriteContacts }) => {
  const { page, contacts } = favouriteContacts;

  contacts.forEach(contact => {
    expect(contact.isFavourite).toBe(true);
  });
});

// Only regular contacts
test('regular contacts', async ({ regularContacts }) => {
  const { page, contacts } = regularContacts;

  contacts.forEach(contact => {
    expect(contact.isFavourite).toBe(false);
  });
});

// Contacts without any tags
test('untagged contacts', async ({ contactsWithoutTags }) => {
  const { page, contacts } = contactsWithoutTags;

  contacts.forEach(contact => {
    expect(contact.tags || []).toHaveLength(0);
  });
});
```

## 🏭 Data Factories

### Contact Factory

```typescript
test('custom contact generation', async ({
  authenticatedPage,
  dataFactory,
  testCleanup,
}) => {
  // Generate custom contacts
  const customContacts = dataFactory.contacts.createMany(5, {
    firstName: 'TestUser',
    isFavourite: true,
  });

  const favouriteContacts = dataFactory.contacts.createFavourites(3);
  const contactsWithEmails = dataFactory.contacts.createWithEmails(10);

  // Use generated data for testing
  expect(customContacts).toHaveLength(5);
  customContacts.forEach(contact => {
    expect(contact.firstName).toBe('TestUser');
    expect(contact.isFavourite).toBe(true);
  });
});
```

### Tag Factory

```typescript
test('custom tag generation', async ({ dataFactory }) => {
  // Generate custom tags
  const customTags = dataFactory.tags.createMany(5, {
    color: '#FF0000',
  });

  const prefixedTags = dataFactory.tags.createWithPrefix('Project', 3);
  const hierarchicalTags = dataFactory.tags.createHierarchy();

  expect(customTags).toHaveLength(5);
  expect(prefixedTags).toHaveLength(3);
  expect(hierarchicalTags).toHaveLength(6);
});
```

### Dataset Factory

```typescript
test('custom dataset generation', async ({ dataFactory }) => {
  // Generate complete datasets
  const smallDataset = dataFactory.datasets.createSmall();
  const searchDataset = dataFactory.datasets.createSearchTestData();
  const performanceDataset = dataFactory.datasets.createPerformanceTestData();

  expect(smallDataset.contacts).toHaveLength(5);
  expect(searchDataset.contacts).toHaveLength(4);
  expect(performanceDataset.contacts).toHaveLength(500);
});
```

## 🧹 Cleanup System

### Automatic Cleanup

```typescript
test('automatic cleanup example', async ({
  authenticatedPage,
  testCleanup,
}) => {
  const dataManager = new TestDataManager(authenticatedPage);

  // Create test data
  const contact = await dataManager.createContact({
    firstName: 'Test',
    lastName: 'User',
  });

  // Register cleanup (automatic with fixtures)
  testCleanup(async () => {
    await dataManager.cleanup();
  });

  // Test runs, cleanup happens automatically
});
```

### Manual Cleanup

```typescript
test('manual cleanup example', async ({ authenticatedPage }) => {
  const dataManager = new TestDataManager(authenticatedPage);

  try {
    // Create and test data
    const contacts = await dataManager.createContacts([...]);

    // Run tests

  } finally {
    // Manual cleanup
    await dataManager.cleanup();
  }
});
```

## 🚀 Performance Features

### Setup Project Authentication

- OAuth flow runs **once** via setup project, not per worker or per test
- Both browser projects (firefox, Mobile Chrome) share the same auth state
- Significant performance improvement (~30-60 seconds saved per full suite run)
- Real authentication state persisted to disk and loaded automatically

### Bulk Operations

- Efficient bulk contact/tag creation
- Optimized for large datasets
- Parallel processing where possible

### Intelligent Fallbacks

- Mock data when API calls fail
- Tests continue running even with backend issues
- Graceful degradation for development

## 📋 Best Practices

### 1. Choose the Right Fixture

```typescript
// ✅ Good: Use specific fixtures for specific needs
test('search functionality', async ({ searchTestData }) => {
  // Uses search-optimized dataset
});

test('performance test', async ({ largeDataSet }) => {
  // Uses large dataset for performance testing
});

// ❌ Avoid: Using large datasets for simple tests
test('simple smoke test', async ({ largeDataSet }) => {
  // Overkill - use smallDataSet instead
});
```

### 2. Leverage Data Factories

```typescript
// ✅ Good: Use factories for custom scenarios
test('custom scenario', async ({
  dataFactory,
  authenticatedPage,
  testCleanup,
}) => {
  const customData = dataFactory.contacts.createMany(3, {
    firstName: 'SpecialCase',
  });

  // Use custom data for specific test needs
});

// ❌ Avoid: Hardcoding test data
test('hardcoded data', async ({ authenticatedPage }) => {
  // Manual data creation - harder to maintain
});
```

### 3. Use Appropriate Cleanup

```typescript
// ✅ Good: Use fixture cleanup for most cases
test('standard test', async ({ contactsWithData, testCleanup }) => {
  // Cleanup handled automatically by fixture
});

// ✅ Good: Manual cleanup for complex scenarios
test('complex scenario', async ({ authenticatedPage }) => {
  const dataManager = new TestDataManager(authenticatedPage);

  try {
    // Complex test logic
  } finally {
    await dataManager.cleanup();
  }
});
```

## 🔧 Extending the System

### Adding New Fixtures

1. **Define the fixture interface** in `fixtures.ts`
2. **Implement the fixture logic** using existing patterns
3. **Add cleanup registration** with `testCleanup`
4. **Document usage** with examples

### Adding New Data Factories

1. **Extend existing factories** or create new ones
2. **Follow naming conventions** (create, createMany, createWith...)
3. **Include realistic data** generation
4. **Add factory to dataFactory fixture**

### Adding New Datasets

1. **Create dataset factory method** in `DataSetFactory`
2. **Define relationships** between contacts and tags
3. **Add corresponding fixture** in `fixtures.ts`
4. **Document use cases** and examples

## 🎯 Migration Guide

See `MIGRATION_GUIDE.md` for detailed instructions on migrating existing tests to the new fixture system.

## 🐛 Troubleshooting

### Common Issues

1. **API Failures**: Fixtures use fallback mock data when APIs fail
2. **Authentication Issues**: Check OAuth provider and login/consent service
3. **Cleanup Issues**: Ensure `testCleanup` is properly registered
4. **Performance Issues**: Use appropriate dataset sizes for test needs

### Debug Mode

Enable debug logging by setting environment variables:

```bash
DEBUG=1 npx playwright test
```

## 📚 Examples

See `example-fixture-usage.spec.ts` for comprehensive examples of all fixture types and usage patterns.
