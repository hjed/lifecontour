import { render, screen, fireEvent } from '@testing-library/react';
import { DailySummaryView } from '../DailySummaryView';
import { useDailySummary, useRegenerateDailySummary } from '@/lib/api/journals';
import { DailySummaryStatus } from '@/types/journals';

// Mock the API hooks
jest.mock('@/lib/api/journals', () => ({
  useDailySummary: jest.fn(),
  useRegenerateDailySummary: jest.fn(),
}));

describe('DailySummaryView', () => {
  const mockDate = '2026-04-29';
  const mockRegenerate = jest.fn();
  const mockRefetch = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (useRegenerateDailySummary as jest.Mock).mockReturnValue({
      mutate: mockRegenerate,
      isPending: false,
    });
  });

  it('renders "Generate AI Summary" button initially', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);

    expect(
      screen.getByTestId(`generate-summary-btn-${mockDate}`)
    ).toBeInTheDocument();
    expect(screen.getByText('Generate AI Summary')).toBeInTheDocument();
  });

  it('shows loading state when fetch is requested and loading', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: null,
      isLoading: true,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);

    // Click generate button
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    // Should enable the hook and show loading
    expect(useDailySummary).toHaveBeenCalledWith(mockDate, { enabled: true });
    expect(
      screen.getByTestId(`summary-loading-${mockDate}`)
    ).toBeInTheDocument();
    expect(screen.getByText('Generating daily summary...')).toBeInTheDocument();
  });

  it('shows error state when fetch fails and retries with refetch', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: null,
      isLoading: false,
      isError: true,
      error: new Error('Network error'),
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    expect(screen.getByTestId(`summary-error-${mockDate}`)).toBeInTheDocument();
    expect(screen.getByText('Failed to load summary')).toBeInTheDocument();
    expect(screen.getByText('Network error')).toBeInTheDocument();

    // Click "Try Again" should call refetch, not regenerate
    fireEvent.click(screen.getByText('Try Again'));
    expect(mockRefetch).toHaveBeenCalled();
    expect(mockRegenerate).not.toHaveBeenCalled();
  });

  it('returns null if status is DISABLED', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            status: DailySummaryStatus.DISABLED,
          },
        },
      },
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    const { container } = render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    expect(container).toBeEmptyDOMElement();
  });

  it('shows dedicated FAILED state with retry action', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            summary_date: mockDate,
            summary_text: null,
            journal_count: 3,
            event_count: 0,
            contact_count: 0,
            status: DailySummaryStatus.FAILED,
          },
        },
      },
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    expect(
      screen.getByTestId(`summary-failed-${mockDate}`)
    ).toBeInTheDocument();
    expect(screen.getByText('Summary generation failed')).toBeInTheDocument();
    expect(
      screen.getByText('The AI was unable to generate a summary for this day.')
    ).toBeInTheDocument();

    // Click "Retry Generation" should call regenerate (force re-generation)
    fireEvent.click(screen.getByText('Retry Generation'));
    expect(mockRegenerate).toHaveBeenCalledWith(mockDate);
  });

  it('renders generated summary and stats correctly', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            summary_date: mockDate,
            summary_text: 'This is a great day.',
            journal_count: 5,
            event_count: 2,
            contact_count: 3,
            mood_average: 8.5,
            status: DailySummaryStatus.GENERATED,
          },
        },
      },
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    expect(screen.getByTestId(`summary-card-${mockDate}`)).toBeInTheDocument();
    expect(screen.getByTestId(`summary-text-${mockDate}`)).toHaveTextContent(
      'This is a great day.'
    );
    expect(screen.getByText('5')).toBeInTheDocument(); // journal count
    expect(screen.getByText('2')).toBeInTheDocument(); // event count
    expect(screen.getByText('3')).toBeInTheDocument(); // contact count
    expect(screen.getByText('8.5/10')).toBeInTheDocument(); // mood average
  });

  it('shows generating badge if status is GENERATING', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            summary_date: mockDate,
            summary_text: 'Still generating...',
            journal_count: 5,
            event_count: 0,
            contact_count: 0,
            status: DailySummaryStatus.GENERATING,
          },
        },
      },
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    expect(screen.getByText('Generating...')).toBeInTheDocument();
    // Refresh button should be disabled
    expect(
      screen.getByTestId(`refresh-summary-btn-${mockDate}`)
    ).toBeDisabled();
  });

  it('calls regenerateSummary when refresh button is clicked', () => {
    (useDailySummary as jest.Mock).mockReturnValue({
      data: {
        data: {
          attributes: {
            summary_date: mockDate,
            summary_text: 'Old summary',
            journal_count: 2,
            event_count: 0,
            contact_count: 0,
            status: DailySummaryStatus.GENERATED,
          },
        },
      },
      isLoading: false,
      isError: false,
      refetch: mockRefetch,
    });

    render(<DailySummaryView date={mockDate} />);
    fireEvent.click(screen.getByTestId(`generate-summary-btn-${mockDate}`));

    const refreshBtn = screen.getByTestId(`refresh-summary-btn-${mockDate}`);
    fireEvent.click(refreshBtn);

    expect(mockRegenerate).toHaveBeenCalledWith(mockDate);
  });
});
