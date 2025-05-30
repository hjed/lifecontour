// Global Jest setup for all projects

// Set timezone to Australian Eastern Time for consistent date testing
process.env.TZ = 'Australia/Sydney';

// Mock environment variables for testing
process.env.NODE_ENV = 'test';
process.env.DATABASE_URL = ':memory:';
process.env.LOG_LEVEL = 'error';

// Global test utilities
global.testUtils = {
  // Australian date format helper
  formatDateAustralian: date => {
    return new Intl.DateTimeFormat('en-AU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }).format(date);
  },

  // Generate test IDs
  generateTestId: () => `test-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,

  // Wait for async operations
  waitFor: ms => new Promise(resolve => setTimeout(resolve, ms)),
};
