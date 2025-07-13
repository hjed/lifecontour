/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import {
  setupPlaceholderPageMocks,
  createPlaceholderPageTests,
  PlaceholderPageConfig
} from '@/test-utils/placeholder-page';
import JournalsPage from '../page';

const pageConfig: PlaceholderPageConfig = {
  title: 'Journals',
  description: 'Your journal entries will appear here.',
  pathname: '/journals',
  implementationText: 'The journal system will be implemented in a future iteration',
  featuresText: 'You&apos;ll be able to create and manage your personal journal entries here',
  iconColorClass: 'text-green-500',
};

describe('JournalsPage', () => {
  setupPlaceholderPageMocks(pageConfig);

  // Generate common tests
  const commonTests = createPlaceholderPageTests(JournalsPage, pageConfig);

  // Execute all common tests
  Object.entries(commonTests).forEach(([testName, testFn]) => {
    it(testName, testFn);
  });

  // Additional page-specific tests
  it('mentions future iteration for implementation', () => {
    render(<JournalsPage />);

    // Verify that it mentions future iteration (not specific like the others)
    expect(screen.getByText(/future iteration/)).toBeInTheDocument();
  });

  it('has consistent styling with other placeholder pages', () => {
    const { container } = render(<JournalsPage />);

    // Check for consistent card structure using more specific selectors
    const cardElement = container.querySelector('[class*="card"]');
    expect(cardElement).toBeInTheDocument();
  });

  it('provides clear user expectations', () => {
    render(<JournalsPage />);

    // Check that the page clearly explains what will be available
    expect(screen.getByText(/create and manage your personal journal entries/)).toBeInTheDocument();
  });
});
