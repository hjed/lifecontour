/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { useParams } from 'next/navigation';
import {
  setupPlaceholderPageMocks,
  createPlaceholderPageTests,
  createDynamicPlaceholderPageTests,
  PlaceholderPageConfig,
} from '@/test-utils/placeholder-page';
import ContactGroupPage from '../page';

const mockUseParams = useParams as jest.MockedFunction<typeof useParams>;

const basePageConfig: Omit<PlaceholderPageConfig, 'title' | 'description'> = {
  pathname: '/contacts/groups/1',
  implementationText:
    'The contact groups functionality will be implemented in ITER1.5-004',
  featuresText:
    'You&apos;ll be able to organize your contacts into groups and view them here',
  iterationText: 'ITER1.5-004',
};

describe('ContactGroupPage', () => {
  setupPlaceholderPageMocks({
    ...basePageConfig,
    title: 'Contact Group 1', // Default for setup
    description: 'Contacts in group 1 will appear here.',
  });

  // Dynamic route tests
  const dynamicTests = createDynamicPlaceholderPageTests(
    ContactGroupPage,
    basePageConfig,
    [
      {
        params: { id: '1' },
        expectedTitle: 'Contact Group 1',
        expectedDescription: 'Contacts in group 1 will appear here.',
      },
      {
        params: { id: '2' },
        expectedTitle: 'Contact Group 2',
        expectedDescription: 'Contacts in group 2 will appear here.',
      },
      {
        params: { id: 'custom-group' },
        expectedTitle: 'Contact Group custom-group',
        expectedDescription: 'Contacts in group custom-group will appear here.',
      },
    ]
  );

  // Execute dynamic tests
  Object.entries(dynamicTests).forEach(([testName, testFn]) => {
    it(testName, testFn);
  });

  // Common tests for a specific group ID
  describe('with group ID 1', () => {
    beforeEach(() => {
      mockUseParams.mockReturnValue({ id: '1' });
    });

    const pageConfigWithId: PlaceholderPageConfig = {
      ...basePageConfig,
      title: 'Contact Group 1',
      description: 'Contacts in group 1 will appear here.',
    };

    const commonTests = createPlaceholderPageTests(
      ContactGroupPage,
      pageConfigWithId
    );

    // Execute all common tests
    Object.entries(commonTests).forEach(([testName, testFn]) => {
      it(testName, testFn);
    });
  });

  // Additional edge case tests
  it('handles missing or undefined group ID gracefully', () => {
    mockUseParams.mockReturnValue({ id: undefined });

    render(<ContactGroupPage />);

    // Should still render but with undefined in the text
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
  });
});
