// eslint-disable-next-line @typescript-eslint/no-require-imports
const nextJest = require('next/jest');

const createJestConfig = nextJest({
  // Provide the path to your Next.js app to load next.config.js and .env files
  dir: './',
});

// Add any custom config to be passed to Jest
const customJestConfig = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testEnvironment: 'jsdom',
  testPathIgnorePatterns: [
    '<rootDir>/.next/',
    '<rootDir>/node_modules/',
    '<rootDir>/tests/',
  ],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '^next/navigation$': '<rootDir>/src/__mocks__/next/navigation.ts',
    // Tiptap (ProseMirror) cannot run in jsdom — mock it so MarkdownEditor
    // wiring is unit-testable. Editor behaviour is covered by Playwright e2e.
    '^@tiptap/react$': '<rootDir>/src/__mocks__/@tiptap/react.tsx',
    '^@tiptap/starter-kit$': '<rootDir>/src/__mocks__/@tiptap/starter-kit.ts',
    '^@tiptap/markdown$': '<rootDir>/src/__mocks__/@tiptap/markdown.ts',
  },
  collectCoverageFrom: [
    'src/**/*.{js,jsx,ts,tsx}',
    '!src/**/*.d.ts',
    '!src/**/*.stories.{js,jsx,ts,tsx}',
    '!src/app/layout.tsx', // Exclude Next.js layout boilerplate
    '!src/app/globals.css', // Exclude CSS files
    '!src/components/ui/**', // Exclude shadcn/ui components (mostly styling)
    '!src/types/**', // Exclude type definitions
    '!src/lib/providers.tsx', // Exclude provider setup
    '!src/app/auth/callback/page.tsx', // Exclude callback page (OAuth flow)
  ],
  coverageThreshold: {
    global: {
      branches: 30,
      functions: 50,
      lines: 50,
      statements: 50,
    },
  },
};

// react-markdown / remark-gfm and the unified (micromark/mdast/hast/unist)
// ecosystem ship as pure ESM. next/jest builds its own transformIgnorePatterns
// (from transpilePackages) and ignores any we set in customJestConfig, so we
// override the resolved config to allow-list these packages for transpilation —
// otherwise their imports throw "Cannot use import statement outside a module".
// pnpm nests real packages under node_modules/.pnpm/<name>@<ver>/..., so the
// allow-list is matched against the .pnpm segment. Extend the list if a new
// package surfaces that error.
const esmPackages = [
  'react-markdown',
  'remark-.*',
  'micromark.*',
  'mdast-.*',
  'hast-.*',
  'unist-.*',
  'unified',
  'bail',
  'is-plain-obj',
  'trough',
  'vfile.*',
  'property-information',
  'space-separated-tokens',
  'comma-separated-tokens',
  'decode-named-character-reference',
  'character-entities.*',
  'html-url-attributes',
  'trim-lines',
  'ccount',
  'escape-string-regexp',
  'markdown-table',
  'zwitch',
  'longest-streak',
  'devlop',
  'estree-util-.*',
  'style-to-js',
  'style-to-object',
  'inline-style-parser',
  'web-namespaces',
  'stringify-entities',
];

// createJestConfig is exported this way to ensure that next/jest can load the Next.js config which is async
module.exports = async () => {
  const config = await createJestConfig(customJestConfig)();
  config.transformIgnorePatterns = [
    `/node_modules/\\.pnpm/(?!(${esmPackages.join('|')})@)`,
    '^.+\\.module\\.(css|sass|scss)$',
  ];
  return config;
};
