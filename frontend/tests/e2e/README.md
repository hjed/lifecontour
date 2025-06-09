# End-to-End Tests for ITER1-004

This directory contains comprehensive Playwright end-to-end tests for the contact management UI (ITER1-004). These tests follow a test-driven development approach and define the expected behavior for the frontend components.

## Test Structure

### Test Files

- **`auth.spec.ts`** - Authentication flow tests

  - OAuth login/logout functionality
  - Session management
  - Protected route access
  - Authentication error handling

- **`contacts-list.spec.ts`** - Contact list and search tests

  - Contact list display
  - Search functionality with MeiliSearch
  - Filtering and pagination
  - Empty states and loading states

- **`contacts-crud.spec.ts`** - Contact CRUD operations

  - Contact creation forms
  - Contact editing forms
  - Contact deletion
  - Form validation
  - Tag management

- **`global-search.spec.ts`** - Global search functionality

  - Global search component
  - Search across entity types
  - Search suggestions and typo tolerance
  - Search result highlighting

- **`responsive-design.spec.ts`** - Responsive design tests
  - Mobile navigation
  - Responsive layouts
  - Touch interactions
  - Accessibility on mobile

### Support Files

- **`pages/`** - Page Object Models

  - `base-page.ts` - Common page functionality
  - `login-page.ts` - Authentication page object
  - `contacts-page.ts` - Contacts list page object
  - `contact-form-page.ts` - Contact form page object

- **`fixtures/`** - Test data and setup

  - `test-data.ts` - Test contacts and validation cases
  - `auth-state.json` - Mock authentication state

- **`utils/`** - Test utilities
  - `api-mocks.ts` - API response mocking

## Running Tests

### Prerequisites

1. Ensure backend is running:

   ```bash
   docker-compose up -d
   ```

2. Ensure frontend is running:
   ```bash
   cd frontend
   pnpm dev
   ```

### Run All E2E Tests

```bash
cd frontend
pnpm test:e2e
```

### Run Tests in UI Mode

```bash
cd frontend
pnpm test:e2e:ui
```

### Run Specific Test File

```bash
cd frontend
npx playwright test auth.spec.ts
```

### Run Tests in Different Browsers

```bash
cd frontend
npx playwright test --project=chromium
npx playwright test --project=firefox
npx playwright test --project=webkit
```

## Test-Driven Development Approach

These tests are designed to **fail initially** since the frontend UI components don't exist yet. This is intentional and follows TDD principles:

1. **Red Phase** - Tests fail because UI components aren't implemented
2. **Green Phase** - Implement minimal UI to make tests pass
3. **Refactor Phase** - Improve implementation while keeping tests passing

## Expected Test Failures (Initial State)

When first running these tests, expect failures for:

- Missing UI components (contact list, forms, search)
- Missing navigation elements
- Missing authentication UI
- Missing responsive design elements

These failures guide the implementation of ITER1-004 components.

## Test Data

Tests use consistent mock data defined in `fixtures/test-data.ts`:

- **Test Contacts** - Sample contacts with various attributes
- **Search Test Cases** - Different search scenarios
- **Validation Cases** - Valid/invalid form inputs
- **Date Format Cases** - Australian date format testing

## API Mocking

Tests use comprehensive API mocking in `utils/api-mocks.ts`:

- **Authentication endpoints** - OAuth providers, login/logout
- **Contact endpoints** - CRUD operations with proper JSON API format
- **Search endpoints** - MeiliSearch responses with highlighting
- **Error scenarios** - Various API error conditions

## Accessibility Testing

Tests include accessibility checks:

- Proper ARIA attributes
- Keyboard navigation
- Touch target sizes (mobile)
- Form labels and validation
- Screen reader compatibility

## Australian Localization

Tests verify Australian English requirements:

- DD/MM/YYYY date formats
- Australian timezone handling
- Proper locale settings

## Browser Coverage

Tests run across multiple browsers:

- **Chromium** - Primary testing browser
- **Firefox** - Cross-browser compatibility
- **WebKit** - Safari compatibility
- **Mobile Chrome** - Mobile testing
- **Mobile Safari** - iOS compatibility

## Debugging Tests

### View Test Results

```bash
npx playwright show-report
```

### Debug Specific Test

```bash
npx playwright test auth.spec.ts --debug
```

### Record Test Video

```bash
npx playwright test --video=on
```

### Take Screenshots

```bash
npx playwright test --screenshot=on
```

## CI/CD Integration

Tests are configured for GitHub Actions:

- Run on all pull requests
- Generate HTML reports
- Upload test artifacts
- Fail builds on test failures

## Implementation Guidelines

When implementing UI components to make these tests pass:

1. **Use exact data-testid attributes** as defined in page objects
2. **Follow responsive design patterns** tested in responsive-design.spec.ts
3. **Implement proper error handling** as tested in error scenarios
4. **Ensure accessibility** as verified in accessibility tests
5. **Support Australian localization** as tested in date format tests

## Next Steps

1. Run tests to see current failures
2. Implement UI components to address failures
3. Iterate until all tests pass
4. Add additional tests for edge cases
5. Integrate with CI/CD pipeline

This test suite provides comprehensive coverage for ITER1-004 and serves as a specification for the expected frontend behavior.
