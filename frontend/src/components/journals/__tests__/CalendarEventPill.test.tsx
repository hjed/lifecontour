import { render, screen } from '@testing-library/react';
import { CalendarEventPill } from '../CalendarEventPill';
import { CalendarEvent } from '@/lib/calendarEventHelpers';
describe('CalendarEventPill', () => {
  const baseEvent: CalendarEvent = {
    id: 'test-event-1',
    title: 'Test Event',
    startTime: '10:00 AM',
    endTime: '11:00 AM',
    date: '2023-10-10',
    isAllDay: false,
    calendarColor: '#ff0000',
    calendarName: 'Personal',
    hasPendingReviews: false,
    isSyncedToGoogle: false,
    isCancelled: false,
    journalTypes: [],
  };

  it('renders correctly in month view', () => {
    render(<CalendarEventPill event={baseEvent} variant='month' />);
    expect(screen.getByText('Test Event')).toBeInTheDocument();
    expect(screen.queryByTestId('sync-indicator')).not.toBeInTheDocument();
    expect(screen.queryByTestId('needs-review-badge')).not.toBeInTheDocument();
  });

  it('renders correctly in week view', () => {
    render(<CalendarEventPill event={baseEvent} variant='week' />);
    expect(screen.getByText('Test Event')).toBeInTheDocument();
    expect(screen.getByText('10:00 AM')).toBeInTheDocument();
  });

  it('renders correctly in day view', () => {
    render(
      <CalendarEventPill
        event={{ ...baseEvent, endTime: '11:00 AM' }}
        variant='day'
      />
    );
    expect(screen.getByText('Test Event')).toBeInTheDocument();
    expect(screen.getByText('10:00 AM')).toBeInTheDocument();
    expect(screen.getByText('11:00 AM')).toBeInTheDocument();
    expect(screen.getByText('Personal')).toBeInTheDocument();
  });

  it('shows sync indicator when isSyncedToGoogle is true', () => {
    const syncedEvent = { ...baseEvent, isSyncedToGoogle: true };
    render(<CalendarEventPill event={syncedEvent} variant='month' />);
    expect(screen.getByTestId('sync-indicator')).toBeInTheDocument();
  });

  it('shows review badge when hasPendingReviews is true in month view', () => {
    const reviewEvent = { ...baseEvent, hasPendingReviews: true };
    render(<CalendarEventPill event={reviewEvent} variant='month' />);
    expect(screen.getByTestId('needs-review-badge')).toBeInTheDocument();
  });

  it('shows review badge when hasPendingReviews is true in week view', () => {
    const reviewEvent = { ...baseEvent, hasPendingReviews: true };
    render(<CalendarEventPill event={reviewEvent} variant='week' />);
    expect(screen.getByTestId('needs-review-badge')).toBeInTheDocument();
  });

  it('shows review badge when hasPendingReviews is true in day view', () => {
    const reviewEvent = { ...baseEvent, hasPendingReviews: true };
    render(<CalendarEventPill event={reviewEvent} variant='day' />);
    const badge = screen.getByTestId('needs-review-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Review');
  });

  it('shows cancelled styling when isCancelled is true', () => {
    const cancelledEvent = { ...baseEvent, isCancelled: true };
    render(<CalendarEventPill event={cancelledEvent} variant='month' />);
    const link = screen.getByRole('link');
    expect(link).toHaveClass('line-through');
    expect(link).toHaveClass('opacity-60');
  });
});
