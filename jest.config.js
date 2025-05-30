/** @type {import('jest').Config} */
module.exports = {
  // Use TypeScript preset
  preset: 'ts-jest/presets/default-esm',

  // Test environment
  testEnvironment: 'node',

  // Module file extensions
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],

  // Transform files
  transform: {
    '^.+\\.(ts|tsx)$': [
      'ts-jest',
      {
        useESM: true,
        tsconfig: {
          module: 'ESNext',
          moduleResolution: 'bundler',
        },
      },
    ],
  },

  // Module name mapping for path aliases
  moduleNameMapping: {
    '^@/(.*)$': '<rootDir>/apps/frontend/src/$1',
    '^@backend/(.*)$': '<rootDir>/apps/backend/src/$1',
    '^@shared/(.*)$': '<rootDir>/packages/shared/src/$1',
    '^@database/(.*)$': '<rootDir>/packages/database/src/$1',
  },

  // Setup files
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],

  // Test patterns
  testMatch: ['<rootDir>/**/__tests__/**/*.(ts|tsx|js)', '<rootDir>/**/*.(test|spec).(ts|tsx|js)'],

  // Ignore patterns
  testPathIgnorePatterns: [
    '<rootDir>/.next/',
    '<rootDir>/node_modules/',
    '<rootDir>/dist/',
    '<rootDir>/build/',
    '<rootDir>/storybook-static/',
  ],

  // Coverage configuration
  collectCoverageFrom: [
    'apps/**/*.{ts,tsx}',
    'packages/**/*.{ts,tsx}',
    '!**/*.d.ts',
    '!**/*.config.{ts,js}',
    '!**/*.stories.{ts,tsx}',
    '!**/node_modules/**',
    '!**/dist/**',
    '!**/build/**',
    '!**/.next/**',
  ],

  // Coverage thresholds (80% requirement)
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80,
    },
  },

  // Coverage reporters
  coverageReporters: ['text', 'lcov', 'html'],

  // Coverage directory
  coverageDirectory: '<rootDir>/coverage',

  // Clear mocks between tests
  clearMocks: true,

  // Restore mocks after each test
  restoreMocks: true,

  // Verbose output
  verbose: true,

  // Projects for different test types
  projects: [
    {
      displayName: 'backend',
      testMatch: ['<rootDir>/apps/backend/**/*.(test|spec).(ts|js)'],
      testEnvironment: 'node',
    },
    {
      displayName: 'frontend',
      testMatch: ['<rootDir>/apps/frontend/**/*.(test|spec).(ts|tsx)'],
      testEnvironment: 'jsdom',
      setupFilesAfterEnv: ['<rootDir>/apps/frontend/jest.setup.js'],
    },
    {
      displayName: 'shared',
      testMatch: ['<rootDir>/packages/shared/**/*.(test|spec).(ts|js)'],
      testEnvironment: 'node',
    },
    {
      displayName: 'database',
      testMatch: ['<rootDir>/packages/database/**/*.(test|spec).(ts|js)'],
      testEnvironment: 'node',
    },
  ],
};
