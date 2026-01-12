/**
 * Tests for JournalTypeBadges component.
 *
 * Tests badge rendering, icon display, and accessibility for all journal types.
 */

import { render, screen } from '@testing-library/react';
import { JournalTypeBadges } from '../JournalTypeBadges';
import { JournalType } from '@/types/journals';

describe('JournalTypeBadges', () => {
  it('renders nothing when types array is empty', () => {
    const { container } = render(<JournalTypeBadges types={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders a single type badge', () => {
    render(<JournalTypeBadges types={[JournalType.NOTE]} />);

    const badge = screen.getByTestId('type-badge-note');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Note');
  });

  it('renders multiple type badges', () => {
    render(
      <JournalTypeBadges
        types={[JournalType.EVENT, JournalType.MOOD_RATING, JournalType.TRAVEL]}
      />
    );

    expect(screen.getByTestId('type-badge-event')).toBeInTheDocument();
    expect(screen.getByTestId('type-badge-mood_rating')).toBeInTheDocument();
    expect(screen.getByTestId('type-badge-travel')).toBeInTheDocument();
  });

  it('displays correct labels for all types', () => {
    render(
      <JournalTypeBadges
        types={[
          JournalType.NOTE,
          JournalType.EVENT,
          JournalType.MOOD_RATING,
          JournalType.PLAN,
          JournalType.TRAVEL,
          JournalType.PHOTO_ALBUM,
        ]}
      />
    );

    expect(screen.getByText('Note')).toBeInTheDocument();
    expect(screen.getByText('Event')).toBeInTheDocument();
    expect(screen.getByText('Mood Rating')).toBeInTheDocument();
    expect(screen.getByText('Plan')).toBeInTheDocument();
    expect(screen.getByText('Travel')).toBeInTheDocument();
    expect(screen.getByText('Photo Album')).toBeInTheDocument();
  });

  it('includes icons for all type badges', () => {
    const { container } = render(
      <JournalTypeBadges types={[JournalType.EVENT, JournalType.MOOD_RATING]} />
    );

    // Check that SVG icons are present (Lucide icons render as SVG)
    const svgIcons = container.querySelectorAll('svg');
    expect(svgIcons.length).toBeGreaterThanOrEqual(2);
  });

  it('has proper accessibility attributes', () => {
    render(<JournalTypeBadges types={[JournalType.NOTE]} />);

    const container = screen.getByLabelText('Journal types');
    expect(container).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(
      <JournalTypeBadges types={[JournalType.NOTE]} className='custom-class' />
    );

    const container = screen.getByTestId('journal-type-badges');
    expect(container).toHaveClass('custom-class');
  });

  it('applies custom test ID', () => {
    render(
      <JournalTypeBadges
        types={[JournalType.NOTE]}
        data-testid='custom-test-id'
      />
    );

    expect(screen.getByTestId('custom-test-id')).toBeInTheDocument();
  });

  it('renders badges in the order provided', () => {
    const { container } = render(
      <JournalTypeBadges
        types={[JournalType.TRAVEL, JournalType.NOTE, JournalType.EVENT]}
      />
    );

    const badges = container.querySelectorAll('[data-testid^="type-badge-"]');
    expect(badges[0]).toHaveAttribute('data-testid', 'type-badge-travel');
    expect(badges[1]).toHaveAttribute('data-testid', 'type-badge-note');
    expect(badges[2]).toHaveAttribute('data-testid', 'type-badge-event');
  });
});
