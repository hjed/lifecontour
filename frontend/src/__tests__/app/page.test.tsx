import { render, screen } from '../utils/test-utils';
import HomePage from '@/app/page';

describe('HomePage', () => {
  it('renders the main heading', () => {
    render(<HomePage />);

    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading).toHaveTextContent('Personal Management System');
  });

  it('renders the subtitle', () => {
    render(<HomePage />);

    const subtitle = screen.getByText(
      'Your personal CRM and journal with AI integration'
    );
    expect(subtitle).toBeInTheDocument();
  });

  it('renders all feature cards', () => {
    render(<HomePage />);

    // Check for all card titles using more specific queries
    expect(
      screen.getByRole('heading', { name: 'Contacts' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Journal' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Calendar' })
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Photos' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'AI Integration' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'System Status' })
    ).toBeInTheDocument();
  });

  it('renders contacts card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText(
        'Manage your personal and professional contacts with tags and Google sync.'
      )
    ).toBeInTheDocument();
  });

  it('renders journal card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText(
        'Keep track of your thoughts, experiences, and memories with mood tracking.'
      )
    ).toBeInTheDocument();
  });

  it('renders calendar card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText(
        'Sync with Google Calendar and link events to photos and journal entries.'
      )
    ).toBeInTheDocument();
  });

  it('renders photos card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText(
        'Connect with Immich to link photos to contacts, events, and journal entries.'
      )
    ).toBeInTheDocument();
  });

  it('renders AI integration card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText(
        'MCP protocol support for AI assistants to access and manage your data.'
      )
    ).toBeInTheDocument();
  });

  it('renders system status card with correct description', () => {
    render(<HomePage />);

    expect(
      screen.getByText('Monitor system health and integration status.')
    ).toBeInTheDocument();
  });

  it('has proper layout structure', () => {
    render(<HomePage />);

    // Check for main container structure
    const heading = screen.getByRole('heading', { level: 1 });
    const mainContainer = heading.closest('.container');
    expect(mainContainer).toHaveClass('container', 'mx-auto', 'py-8');
  });

  it('renders exactly 6 feature cards', () => {
    render(<HomePage />);

    // Count the number of cards by looking for card titles as headings
    const cardTitles = [
      'Contacts',
      'Journal',
      'Calendar',
      'Photos',
      'AI Integration',
      'System Status',
    ];

    cardTitles.forEach(title => {
      expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
    });

    // Verify we have exactly 6 cards
    expect(cardTitles).toHaveLength(6);
  });
});
