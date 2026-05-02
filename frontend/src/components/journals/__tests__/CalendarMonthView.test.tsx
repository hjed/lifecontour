import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CalendarMonthView } from '../CalendarMonthView';
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

describe('CalendarMonthView', () => {
  const defaultProps = {
    year: 2026,
    month: 3, // April (0-indexed)
    events: [] as CalendarEvent[],
    onMonthChange: jest.fn(),
    onDayClick: jest.fn(),
    isLoading: false,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders month heading with correct month and year', () => {
    render(<CalendarMonthView {...defaultProps} />);

    expect(screen.getByText('April 2026')).toBeInTheDocument();
  });

  it('renders weekday headers', () => {
    render(<CalendarMonthView {...defaultProps} />);

    expect(screen.getByText('Mon')).toBeInTheDocument();
    expect(screen.getByText('Tue')).toBeInTheDocument();
    expect(screen.getByText('Wed')).toBeInTheDocument();
    expect(screen.getByText('Thu')).toBeInTheDocument();
    expect(screen.getByText('Fri')).toBeInTheDocument();
    expect(screen.getByText('Sat')).toBeInTheDocument();
    expect(screen.getByText('Sun')).toBeInTheDocument();
  });

  it('renders all days of the month as grid cells', () => {
    render(<CalendarMonthView {...defaultProps} />);

    // April 2026 has 30 days - verify by testid
    expect(screen.getByTestId('day-cell-2026-04-01')).toBeInTheDocument();
    expect(screen.getByTestId('day-cell-2026-04-30')).toBeInTheDocument();
  });

  it('renders event pills with calendar colours', () => {
    const events = [
      createMockEvent({
        id: '1',
        title: 'Blue Event',
        calendarColor: '#3b82f6',
      }),
    ];

    render(<CalendarMonthView {...defaultProps} events={events} />);

    const eventPill = screen.getByText('Blue Event');
    expect(eventPill).toBeInTheDocument();
  });

  it('shows "+N more" overflow when more than 3 events on a day', () => {
    const events = [
      createMockEvent({ id: '1', title: 'Event 1', date: '2026-04-15' }),
      createMockEvent({ id: '2', title: 'Event 2', date: '2026-04-15' }),
      createMockEvent({ id: '3', title: 'Event 3', date: '2026-04-15' }),
      createMockEvent({ id: '4', title: 'Event 4', date: '2026-04-15' }),
    ];

    render(<CalendarMonthView {...defaultProps} events={events} />);

    expect(screen.getByText('+1 more')).toBeInTheDocument();
  });

  it("highlights today's date", () => {
    const today = new Date();
    const year = today.getFullYear();
    const month = today.getMonth();

    render(<CalendarMonthView {...defaultProps} year={year} month={month} />);

    const todayCell = screen.getByTestId(
      `day-cell-${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
    );
    expect(todayCell).toHaveAttribute('data-today', 'true');
  });

  it('navigates to previous month on prev click', async () => {
    const user = userEvent.setup();
    const onMonthChange = jest.fn();

    render(
      <CalendarMonthView {...defaultProps} onMonthChange={onMonthChange} />
    );

    await user.click(screen.getByRole('button', { name: /previous month/i }));
    expect(onMonthChange).toHaveBeenCalledWith(2026, 2); // March
  });

  it('navigates to next month on next click', async () => {
    const user = userEvent.setup();
    const onMonthChange = jest.fn();

    render(
      <CalendarMonthView {...defaultProps} onMonthChange={onMonthChange} />
    );

    await user.click(screen.getByRole('button', { name: /next month/i }));
    expect(onMonthChange).toHaveBeenCalledWith(2026, 4); // May
  });

  it('shows cancelled events with appropriate styling', () => {
    const events = [
      createMockEvent({ id: '1', title: 'Cancelled Event', isCancelled: true }),
    ];

    render(<CalendarMonthView {...defaultProps} events={events} />);

    const link = screen.getByRole('link', { name: /cancelled event/i });
    expect(link).toHaveClass('line-through');
  });

  it('calls onDayClick when day cell is clicked', async () => {
    const user = userEvent.setup();
    const onDayClick = jest.fn();

    render(<CalendarMonthView {...defaultProps} onDayClick={onDayClick} />);

    await user.click(screen.getByTestId('day-cell-2026-04-15'));
    expect(onDayClick).toHaveBeenCalledWith('2026-04-15');
  });

  it('renders events as links to journal detail', () => {
    const events = [createMockEvent({ id: '42', title: 'Linked Event' })];

    render(<CalendarMonthView {...defaultProps} events={events} />);

    const link = screen.getByRole('link', { name: /linked event/i });
    expect(link).toHaveAttribute('href', '/journals/42');
  });

  it('has correct ARIA grid role', () => {
    render(<CalendarMonthView {...defaultProps} />);

    expect(screen.getByRole('grid')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    render(<CalendarMonthView {...defaultProps} isLoading={true} />);

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });
});
