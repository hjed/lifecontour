/**
 * @jest-environment jsdom
 */

import {
  setupPlaceholderPageMocks,
  createPlaceholderPageTests,
  PlaceholderPageConfig
} from '@/test-utils/placeholder-page';
import FavouritesPage from '../page';

const pageConfig: PlaceholderPageConfig = {
  title: 'Favourite Contacts',
  description: 'Your starred contacts will appear here.',
  pathname: '/contacts/favourites',
  implementationText: 'The favourites functionality will be implemented in ITER1.5-004',
  featuresText: 'You&apos;ll be able to star your important contacts and view them here',
  iterationText: 'ITER1.5-004',
};

describe('FavouritesPage', () => {
  setupPlaceholderPageMocks(pageConfig);

  // Generate common tests
  const commonTests = createPlaceholderPageTests(FavouritesPage, pageConfig);

  // Execute all common tests
  Object.entries(commonTests).forEach(([testName, testFn]) => {
    it(testName, testFn);
  });

});
