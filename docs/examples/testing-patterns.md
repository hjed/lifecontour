# Testing Patterns - Personal CRM & Journal System

This document provides detailed testing examples and patterns for the Personal
CRM & Journal System.

## Jest Configuration

```javascript
// jest.config.js
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src', '<rootDir>/tests'],
  testMatch: ['**/__tests__/**/*.ts', '**/?(*.)+(spec|test).ts'],
  collectCoverageFrom: ['src/**/*.ts', '!src/**/*.d.ts', '!src/types/**/*'],
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80,
    },
  },
};
```

## Unit Testing Patterns

- define each case using `define`
- clear mocks in an `afterEach`
- only one `it` per bottom level `describe`

### Domain Entity Testing

```typescript
// contacts/domain/entities/__tests__/Contact.test.ts
import { Contact } from '../Contact';
import { Email } from '../value-objects/Email';

describe('Contact Entity', () => {
  describe('when creating a contact', () => {
    it('should create contact with valid data', () => {
      const email = Email.create('john@example.com');
      const contact = Contact.create({
        name: 'John Smith',
        email: email.getValue(),
      });

      expect(contact.isSuccess()).toBe(true);
      expect(contact.getValue().getName()).toBe('John Smith');
    });
  });

  describe('when creating a contact with invalid email format', () => {
    it('should reject', () => {
      const result = Contact.create({
        name: 'John Smith',
        email: 'invalid-email',
      });

      expect(result.isFailure()).toBe(true);
      expect(result.getError()).toContain('Invalid email');
    });
  });
});
```

### Application Component Layer Testing

- define each case using `define`
- clear mocks in an `afterEach`
- only one `it` per bottom level `describe`

## Component Testing with Storybook

### Contact Card Stories

```typescript
// components/ContactCard.stories.ts
import type { Meta, StoryObj } from '@storybook/react';
import { within, userEvent, expect } from '@storybook/test';
import { ContactCard } from './ContactCard';

const meta: Meta<typeof ContactCard> = {
  title: 'Components/ContactCard',
  component: ContactCard,
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component:
          'Contact card with Australian localization and accessibility support.',
      },
    },
  },
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    contact: {
      id: '1',
      name: 'Sarah Wilson',
      email: 'sarah@example.com',
      phone: '0400 123 456',
      company: 'Melbourne Tech Solutions',
      tags: [
        { id: '1', name: 'Work', colour: '#3b82f6' },
        { id: '2', name: 'Important', colour: '#ef4444' },
      ],
    },
  },
};

export const InteractiveTest: Story = {
  args: Default.args,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    // Test dropdown menu
    const menuButton = canvas.getByRole('button', { name: /open menu/i });
    await userEvent.click(menuButton);

    await expect(canvas.getByText('Edit Contact')).toBeInTheDocument();
    await expect(canvas.getByText('Move to Bin')).toBeInTheDocument();
  },
};
```

## End-to-End Testing with Playwright

### Contact Management Flow

```typescript
// tests/e2e/contact-management.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Contact Management', () => {
  test('should create and manage contact with Australian formatting', async ({
    page,
  }) => {
    await page.goto('/contacts');

    // Create new contact
    await page.click('[data-testid="add-contact-button"]');
    await page.fill('[data-testid="contact-name"]', 'Sarah Wilson');
    await page.fill('[data-testid="contact-email"]', 'sarah@example.com');
    await page.fill('[data-testid="contact-phone"]', '0400 123 456');

    // Add tags
    await page.click('[data-testid="add-tag-button"]');
    await page.fill('[data-testid="tag-input"]', 'Work');
    await page.press('[data-testid="tag-input"]', 'Enter');

    await page.click('[data-testid="save-contact"]');

    // Verify contact appears with Australian formatting
    await expect(page.locator('[data-testid="contact-list"]')).toContainText(
      'Sarah Wilson'
    );
    await expect(page.locator('[data-testid="contact-tags"]')).toContainText(
      'Work'
    );

    // Test Australian date formatting (DD/MM/YYYY)
    const dateElement = page.locator('[data-testid="contact-created-date"]');
    await expect(dateElement).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  test('should handle sync errors gracefully', async ({ page }) => {
    // Mock network failure
    await page.route('**/api/sync/google', route => route.abort());

    await page.goto('/contacts');
    await page.click('[data-testid="sync-google-button"]');

    // Should show error message
    await expect(page.locator('[data-testid="error-message"]')).toContainText(
      'Sync failed'
    );
    await expect(page.locator('[data-testid="retry-button"]')).toBeVisible();
  });
});
```

## Integration Testing

### Database Integration

```typescript
// tests/integration/contact-repository.test.ts
describe('SqlContactRepository Integration', () => {
  let db: Database;
  let repository: SqlContactRepository;

  beforeEach(async () => {
    db = await createTestDatabase();
    repository = new SqlContactRepository(db);
  });

  afterEach(async () => {
    await db.close();
  });

  it('should persist and retrieve contacts', async () => {
    const contact = Contact.create({
      name: 'John Doe',
      email: 'john@example.com',
    }).getValue();

    await repository.save(contact);
    const retrieved = await repository.findById(contact.getId());

    expect(retrieved).toBeDefined();
    expect(retrieved!.getName()).toBe('John Doe');
  });
});
```

## Mock Utilities

### Repository Mocks

```typescript
// tests/utils/mocks.ts
export function createMockContactRepository(): jest.Mocked<ContactRepository> {
  return {
    save: jest.fn(),
    findById: jest.fn(),
    findByEmail: jest.fn(),
    findAll: jest.fn(),
    delete: jest.fn(),
  };
}

export function createMockEventBus(): jest.Mocked<EventBus> {
  return {
    publish: jest.fn(),
    subscribe: jest.fn(),
  };
}
```

## Test Data Builders

```typescript
// tests/builders/ContactBuilder.ts
export class ContactBuilder {
  private data: Partial<ContactData> = {};

  withName(name: string): ContactBuilder {
    this.data.name = name;
    return this;
  }

  withEmail(email: string): ContactBuilder {
    this.data.email = email;
    return this;
  }

  build(): Contact {
    return Contact.create({
      name: this.data.name || 'Test Contact',
      email: this.data.email || 'test@example.com',
      ...this.data,
    }).getValue();
  }
}

// Usage
const contact = new ContactBuilder()
  .withName('John Doe')
  .withEmail('john@example.com')
  .build();
```
