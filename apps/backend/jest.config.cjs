/** @type {import('jest').Config} */
module.exports = {
  // Use TypeScript preset with ESM support
  preset: 'ts-jest/presets/default-esm',

  // Test environment
  testEnvironment: 'node',

  // Enable ESM support
  extensionsToTreatAsEsm: ['.ts'],

  // Module file extensions
  moduleFileExtensions: ['ts', 'js', 'json'],

  // Transform files
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      useESM: true,
      tsconfig: {
        module: 'ESNext',
        moduleResolution: 'bundler',
        allowImportingTsExtensions: false,
        verbatimModuleSyntax: false,
      },
    }],
  },

  // Module name mapping for path aliases
  moduleNameMapper: {
    '^@backend/(.*)$': '<rootDir>/src/$1',
    '^@shared/(.*)$': '<rootDir>/../../packages/shared/src/$1',
    '^@database/(.*)$': '<rootDir>/../../packages/database/src/$1',
  },

  // Setup files
  setupFiles: ['reflect-metadata'],
  setupFilesAfterEnv: ['<rootDir>/../../jest.setup.js'],

  // Test patterns
  testMatch: [
    '<rootDir>/src/**/__tests__/**/*.ts',
    '<rootDir>/src/**/*.(test|spec).ts',
  ],

  // Ignore patterns
  testPathIgnorePatterns: [
    '<rootDir>/node_modules/',
    '<rootDir>/dist/',
  ],

  // Coverage configuration
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.d.ts',
    '!src/**/*.config.ts',
    '!src/**/index.ts',
  ],

  // Coverage thresholds
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

  // Handle globals
  globals: {
    'ts-jest': {
      useESM: true,
    },
  },
};
