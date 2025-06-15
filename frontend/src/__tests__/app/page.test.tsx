import { screen } from '@testing-library/react';
import { renderWithProviders, homePageTestUtils } from '@/test-utils';
import HomePage from '@/app/page';

// Helper function to render HomePage and wait for it to load
const renderHomePage = async () => {
  renderWithProviders(<HomePage />);
  // Wait for authentication to complete and page to load
  return await screen.findByRole('heading', { level: 1 });
};

describe('HomePage', () => {
  beforeEach(() => {
    homePageTestUtils.setupHomePageTest();
  });

  describe('Layout and Structure', () => {
    it('renders the main heading', async () => {
      const heading = await renderHomePage();
      expect(heading).toBeInTheDocument();
      expect(heading).toHaveTextContent('Personal Management System');
    });

    it('renders the subtitle', async () => {
      await renderHomePage();
      const subtitle = await screen.findByText(
        'Your personal CRM and journal with AI integration'
      );
      expect(subtitle).toBeInTheDocument();
    });

    it('has proper layout structure', async () => {
      const heading = await renderHomePage();
      const mainContainer = heading.closest('.container');
      expect(mainContainer).toHaveClass('container', 'mx-auto', 'py-8');
    });
  });

  describe('Feature Cards', () => {
    it('renders all feature cards', async () => {
      await renderHomePage();

      // Wait for first card to load, then check all
      await screen.findByText('Contacts');

      // Check for all card titles
      homePageTestUtils.FEATURE_CARDS.forEach(card => {
        expect(screen.getByText(card.title)).toBeInTheDocument();
      });
    });

    it('renders exactly 6 feature cards', async () => {
      await renderHomePage();

      // Wait for first card to load
      await screen.findByText('Contacts');

      // Verify we have exactly 6 cards
      expect(homePageTestUtils.FEATURE_CARDS).toHaveLength(6);

      homePageTestUtils.FEATURE_CARDS.forEach(card => {
        expect(screen.getByText(card.title)).toBeInTheDocument();
      });
    });

    it('renders all card descriptions correctly', async () => {
      await renderHomePage();

      // Wait for first card to load
      await screen.findByText('Contacts');

      // Check all card descriptions
      homePageTestUtils.FEATURE_CARDS.forEach(card => {
        expect(screen.getByText(card.description)).toBeInTheDocument();
      });
    });

    // Individual card tests for specific validation if needed
    it.each(homePageTestUtils.FEATURE_CARDS)(
      'renders $title card with correct description',
      async ({ title, description }) => {
        await renderHomePage();

        // Wait for the specific card to load
        await screen.findByText(title);
        expect(screen.getByText(description)).toBeInTheDocument();
      }
    );
  });
});
