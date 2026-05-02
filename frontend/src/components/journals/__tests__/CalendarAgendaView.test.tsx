import { render, screen } from '@testing-library/react';
import { CalendarAgendaView } from '../CalendarAgendaView';
import { CalendarEvent } from '@/lib/calendarEventHelpers';
import { JournalType } from '@/types/journals';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  };
});

const createMockEvent = (
  overrides: Partial<CalendarEvent> = {}
): CalendarEvent => ({
  id: '1',
  title: 'Test Event',
  date: '2026-04-15',
  endDate: '2026-04-15',
  isMultiDay: false,
  startTime: '10:00',
  endTime: '11:00',
  isAllDay: false,
  calendarColor: '#3b82f6',
  calendarName: 'Personal',
  isCancelled: false,
  journalTypes: [JournalType.EVENT],
  hasPendingReviews: false,
  isSyncedToGoogle: false,
  ...overrides,
});

describe('CalendarAgendaView', () => {
  const defaultProps = {
    events: [] as CalendarEvent[],
    isLoading: false,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders day headings for days with events', () => {
    const events = [
      createMockEvent({ id: '1', title: 'Event A', date: '2026-04-15' }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    // Should show the formatted date heading
    expect(screen.getByText(/Wednesday, April 15/i)).toBeInTheDocument();
  });

  it('renders event rows with time range', () => {
    const events = [
      createMockEvent({
        id: '1',
        title: 'Timed Event',
        startTime: '10:00',
        endTime: '11:30',
      }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    expect(screen.getByText('10:00 – 11:30')).toBeInTheDocument();
    expect(screen.getByText('Timed Event')).toBeInTheDocument();
  });

  it('shows "All day" for all-day events', () => {
    const events = [
      createMockEvent({
        id: '1',
        title: 'Full Day Event',
        isAllDay: true,
        startTime: null,
        endTime: null,
      }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    expect(screen.getByText('All day')).toBeInTheDocument();
  });

  it('shows calendar colour dot', () => {
    const events = [createMockEvent({ id: '1', calendarColor: '#ef4444' })];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    const dot = screen.getByTestId('calendar-dot-1');
    expect(dot).toHaveStyle({ backgroundColor: '#ef4444' });
  });

  it('shows cancelled events with strikethrough', () => {
    const events = [
      createMockEvent({
        id: '1',
        title: 'Cancelled Meeting',
        isCancelled: true,
      }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    const eventTitle = screen.getByText('Cancelled Meeting');
    expect(eventTitle).toHaveClass('line-through');
  });

  it('renders events as links to journal detail', () => {
    const events = [createMockEvent({ id: '42', title: 'Linked Event' })];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    const link = screen.getByRole('link', { name: /linked event/i });
    expect(link).toHaveAttribute('href', '/journals/42');
  });

  it('groups multiple events under the same day heading', () => {
    const events = [
      createMockEvent({
        id: '1',
        title: 'Morning Event',
        date: '2026-04-15',
        startTime: '09:00',
      }),
      createMockEvent({
        id: '2',
        title: 'Afternoon Event',
        date: '2026-04-15',
        startTime: '14:00',
      }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    // Both events visible under one heading
    expect(screen.getByText('Morning Event')).toBeInTheDocument();
    expect(screen.getByText('Afternoon Event')).toBeInTheDocument();

    // Only one day heading
    const headings = screen.getAllByText(/April 15/i);
    expect(headings).toHaveLength(1);
  });

  it('sorts events by date ascending', () => {
    const events = [
      createMockEvent({ id: '2', title: 'Later Event', date: '2026-04-16' }),
      createMockEvent({ id: '1', title: 'Earlier Event', date: '2026-04-14' }),
    ];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    const allLinks = screen.getAllByRole('link');
    expect(allLinks[0]).toHaveTextContent('Earlier Event');
    expect(allLinks[1]).toHaveTextContent('Later Event');
  });

  it('shows empty state when no events', () => {
    render(<CalendarAgendaView {...defaultProps} events={[]} />);

    expect(screen.getByText(/no events/i)).toBeInTheDocument();
  });

  it('shows loading state', () => {
    render(<CalendarAgendaView {...defaultProps} isLoading={true} />);

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('has accessible list structure', () => {
    const events = [createMockEvent({ id: '1', title: 'Accessible Event' })];

    render(<CalendarAgendaView {...defaultProps} events={events} />);

    expect(screen.getByRole('list')).toBeInTheDocument();
    expect(screen.getByRole('listitem')).toBeInTheDocument();
  });
});
