/**
 * Tests for JournalTypeSection component.
 *
 * Tests collapsible functionality, type-specific rendering, and accessibility.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalTypeSection } from '../JournalTypeSection';
import { JournalType } from '@/types/journals';
import type { MoodData } from '@/types/journals';

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

jest.mock('@/lib/api/journals', () => ({
  useCalendars: () => ({ data: [], isLoading: false }),
}));

describe('JournalTypeSection', () => {
  const mockJournalId = '123';

  it('renders with collapsed state by default', () => {
    render(
      <JournalTypeSection journalId={mockJournalId} type={JournalType.EVENT} />
    );

    const trigger = screen.getByTestId('type-section-trigger-event');
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-label', 'Expand Event Details');
  });

  it('renders with expanded state when defaultOpen is true', () => {
    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.MOOD_RATING}
        defaultOpen={true}
      />
    );

    const trigger = screen.getByTestId('type-section-trigger-mood_rating');
    expect(trigger).toHaveAttribute('aria-label', 'Collapse Mood & Energy');

    // Content should be visible (type-specific editor)
    const content = screen.getByTestId('mood-rating-type-editor');
    expect(content).toBeInTheDocument();
  });

  it('toggles open/closed state when clicked', async () => {
    const user = userEvent.setup();

    render(
      <JournalTypeSection journalId={mockJournalId} type={JournalType.PLAN} />
    );

    const trigger = screen.getByTestId('type-section-trigger-plan');

    // Initially collapsed
    expect(trigger).toHaveAttribute('aria-label', 'Expand Plan Documents');

    // Click to expand
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-label', 'Collapse Plan Documents');
    expect(screen.getByTestId('plan-type-editor')).toBeInTheDocument();

    // Click to collapse
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-label', 'Expand Plan Documents');
  });

  it('displays correct section labels for all types', () => {
    const types = [
      { type: JournalType.NOTE, label: 'Note Details' },
      { type: JournalType.EVENT, label: 'Event Details' },
      { type: JournalType.MOOD_RATING, label: 'Mood & Energy' },
      { type: JournalType.PLAN, label: 'Plan Documents' },
      { type: JournalType.TRAVEL, label: 'Travel Itinerary' },
      { type: JournalType.PHOTO_ALBUM, label: 'Photo Album' },
      { type: JournalType.ABSEILING_TRIP, label: 'Abseiling Trip' },
      { type: JournalType.CANYONING, label: 'Canyoning' },
      { type: JournalType.CLIMBING, label: 'Climbing' },
      { type: JournalType.KAYAKING, label: 'Kayaking' },
      { type: JournalType.CROSS_COUNTRY_SKIING, label: 'Cross-Country Skiing' },
    ];

    types.forEach(({ type, label }) => {
      const { unmount } = render(
        <JournalTypeSection journalId={mockJournalId} type={type} />
      );
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    });
  });

  it('renders type-specific content when expanded', () => {
    const moodData: MoodData = {
      mood_value: 8,
      mood_label: 'Happy',
      energy_level: 7,
    };

    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.MOOD_RATING}
        typeData={moodData}
        defaultOpen={true}
      />
    );

    const content = screen.getByTestId('mood-rating-type-editor');
    expect(content).toBeInTheDocument();

    // Verify data is passed to the editor
    expect(screen.getByTestId('mood-value-display')).toHaveTextContent('8');
    expect(screen.getByTestId('mood-label-input')).toHaveValue('Happy');
    expect(screen.getByTestId('energy-level-display')).toHaveTextContent('7');
  });

  it('renders canyoning content when expanded', () => {
    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.CANYONING}
        typeData={{ french_grade: 'v3a2IV**' }}
        defaultOpen={true}
      />
    );

    expect(screen.getByTestId('canyoning-type-editor')).toBeInTheDocument();
    expect(screen.getByText('v3a2IV**')).toBeInTheDocument();
  });

  it('renders abseiling content when expanded', () => {
    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.ABSEILING_TRIP}
        typeData={{ number_of_abseils: 4, total_length: 120 }}
        defaultOpen={true}
      />
    );

    expect(
      screen.getByTestId('abseiling-trip-type-editor')
    ).toBeInTheDocument();
    expect(screen.getByText('120 m')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.EVENT}
        className='custom-class'
      />
    );

    const section = screen.getByTestId('type-section-event');
    expect(section).toHaveClass('custom-class');
  });

  it('applies custom test ID', () => {
    render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.EVENT}
        data-testid='custom-test-id'
      />
    );

    expect(screen.getByTestId('custom-test-id')).toBeInTheDocument();
  });

  it('shows chevron icons for expand/collapse state', () => {
    const { container, rerender } = render(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.EVENT}
        defaultOpen={false}
      />
    );

    // Collapsed state should show ChevronRight
    let chevrons = container.querySelectorAll('svg');
    expect(chevrons.length).toBeGreaterThan(0);

    // Expanded state should show ChevronDown
    rerender(
      <JournalTypeSection
        journalId={mockJournalId}
        type={JournalType.EVENT}
        defaultOpen={true}
      />
    );

    chevrons = container.querySelectorAll('svg');
    expect(chevrons.length).toBeGreaterThan(0);
  });

  it('maintains state across re-renders', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <JournalTypeSection journalId={mockJournalId} type={JournalType.EVENT} />
    );

    const trigger = screen.getByTestId('type-section-trigger-event');

    // Expand
    await user.click(trigger);
    expect(screen.getByTestId('event-type-editor')).toBeInTheDocument();

    // Re-render with same props
    rerender(
      <JournalTypeSection journalId={mockJournalId} type={JournalType.EVENT} />
    );

    // Should still be expanded
    expect(screen.getByTestId('event-type-editor')).toBeInTheDocument();
  });
});
