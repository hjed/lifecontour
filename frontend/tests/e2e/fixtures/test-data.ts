/**
 * Test data fixtures for Playwright tests.
 *
 * Provides consistent test data for contact management tests.
 */

export interface TestContact {
  id?: number;
  firstName: string;
  lastName: string;
  email?: string;
  phone?: string;
  company?: string;
  tags?: string[];
  notes?: string;
}

export interface TestUser {
  id: string;
  email: string;
  name: string;
  provider: string;
}

/**
 * Test contacts for various scenarios
 */
export const testContacts: TestContact[] = [
  {
    id: 1,
    firstName: 'John',
    lastName: 'Smith',
    email: 'john.smith@example.com',
    phone: '+61 2 9876 5432',
    company: 'Acme Corp',
    tags: ['work', 'client'],
    notes: 'Primary contact for Acme Corp project',
  },
  {
    id: 2,
    firstName: 'Sarah',
    lastName: 'Johnson',
    email: 'sarah.johnson@example.com',
    phone: '+61 3 8765 4321',
    company: 'Tech Solutions',
    tags: ['work', 'vendor'],
    notes: 'Technical lead for integration project',
  },
  {
    id: 3,
    firstName: 'Michael',
    lastName: 'Brown',
    email: 'mike.brown@personal.com',
    phone: '+61 4 1234 5678',
    tags: ['personal', 'friend'],
    notes: 'University friend, lives in Melbourne',
  },
  {
    id: 4,
    firstName: 'Emma',
    lastName: 'Wilson',
    email: 'emma.wilson@startup.io',
    company: 'Innovation Labs',
    tags: ['work', 'startup'],
    notes: 'Potential collaboration opportunity',
  },
];

/**
 * Test user for authentication
 */
export const testUser: TestUser = {
  id: 'test-user-123',
  email: 'test@example.com',
  name: 'Test User',
  provider: 'github',
};

/**
 * Search test data
 */
export const searchTestCases = [
  {
    query: 'john',
    expectedResults: ['John Smith'],
    description: 'Search by first name',
  },
  {
    query: 'smith',
    expectedResults: ['John Smith'],
    description: 'Search by last name',
  },
  {
    query: 'acme',
    expectedResults: ['John Smith'],
    description: 'Search by company',
  },
  {
    query: 'work',
    expectedResults: ['John Smith', 'Sarah Johnson', 'Emma Wilson'],
    description: 'Search by tag',
  },
  {
    query: 'nonexistent',
    expectedResults: [],
    description: 'Search with no results',
  },
];

/**
 * Form validation test cases
 */
export const validationTestCases = {
  firstName: {
    valid: ['John', 'Sarah-Jane', "O'Connor"],
    invalid: ['', '   ', 'A'.repeat(101)],
  },
  lastName: {
    valid: ['Smith', 'Johnson-Brown', "O'Malley"],
    invalid: ['', '   ', 'B'.repeat(101)],
  },
  email: {
    valid: ['test@example.com', 'user.name+tag@domain.co.uk'],
    invalid: ['invalid-email', '@domain.com', 'user@', ''],
  },
  phone: {
    valid: ['+61 2 9876 5432', '0412 345 678', '+1 555 123 4567'],
    invalid: ['invalid-phone', '123', ''],
  },
};

/**
 * Australian date format test cases
 */
export const dateFormatTestCases = [
  {
    input: new Date('2024-01-15'),
    expected: '15/01/2024',
    description: 'Standard date format',
  },
  {
    input: new Date('2024-12-31'),
    expected: '31/12/2024',
    description: 'End of year date',
  },
];
