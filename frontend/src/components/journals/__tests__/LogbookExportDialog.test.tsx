import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LogbookExportDialog } from '../LogbookExportDialog';
import { useExportOutdoorLogbook } from '@/lib/api/journals';

// Mock dependencies
jest.mock('@/lib/api/journals', () => ({
  useExportOutdoorLogbook: jest.fn(),
}));

describe('LogbookExportDialog', () => {
  let mutateMock: jest.Mock;
  const onOpenChangeMock = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mutateMock = jest.fn();

    (useExportOutdoorLogbook as jest.Mock).mockReturnValue({
      mutate: mutateMock,
      isPending: false,
    });
  });

  it('renders dialog with title and description when open', () => {
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    expect(screen.getByText('Export Outdoor Logbook')).toBeInTheDocument();
    expect(
      screen.getByText(/Generate a PDF logbook of your outdoor activities/)
    ).toBeInTheDocument();
  });

  it('does not render dialog content when closed', () => {
    render(
      <LogbookExportDialog open={false} onOpenChange={onOpenChangeMock} />
    );

    expect(
      screen.queryByText('Export Outdoor Logbook')
    ).not.toBeInTheDocument();
  });

  it('renders activity type checkboxes', () => {
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    expect(screen.getByText('Bushwalking')).toBeInTheDocument();
    expect(screen.getByText('Canyoning')).toBeInTheDocument();
    expect(screen.getByText('Caving')).toBeInTheDocument();
    expect(screen.getByText('Climbing')).toBeInTheDocument();
  });

  it('renders export and cancel buttons', () => {
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    expect(
      screen.getByRole('button', { name: /Export PDF/i })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument();
  });

  it('calls mutate with empty filters when no filters selected', async () => {
    const user = userEvent.setup();
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    await user.click(screen.getByRole('button', { name: /Export PDF/i }));

    expect(mutateMock).toHaveBeenCalledWith(
      {},
      expect.objectContaining({
        onSuccess: expect.any(Function),
      })
    );
  });

  it('includes selected activity types in export filters', async () => {
    const user = userEvent.setup();
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    // Select Bushwalking and Caving
    const bushwalkingCheckbox = screen.getByTestId('export-type-BUSHWALKING');
    const cavingCheckbox = screen.getByTestId('export-type-CAVING');
    await user.click(bushwalkingCheckbox);
    await user.click(cavingCheckbox);

    await user.click(screen.getByRole('button', { name: /Export PDF/i }));

    expect(mutateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        activity_types: ['BUSHWALKING', 'CAVING'],
      }),
      expect.any(Object)
    );
  });

  it('shows clear filters button when types are selected', async () => {
    const user = userEvent.setup();
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    // Initially no clear button
    expect(
      screen.queryByTestId('export-clear-filters')
    ).not.toBeInTheDocument();

    // Select a type
    await user.click(screen.getByTestId('export-type-CANYONING'));

    // Clear button should appear
    expect(screen.getByTestId('export-clear-filters')).toBeInTheDocument();
  });

  it('clears selected types when clear filters is clicked', async () => {
    const user = userEvent.setup();
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    // Select a type
    await user.click(screen.getByTestId('export-type-CANYONING'));
    expect(screen.getByTestId('export-clear-filters')).toBeInTheDocument();

    // Click clear
    await user.click(screen.getByTestId('export-clear-filters'));

    // Clear button should disappear
    expect(
      screen.queryByTestId('export-clear-filters')
    ).not.toBeInTheDocument();

    // Export should have empty filters
    await user.click(screen.getByRole('button', { name: /Export PDF/i }));
    expect(mutateMock).toHaveBeenCalledWith({}, expect.any(Object));
  });

  it('shows loading state when export is pending', () => {
    (useExportOutdoorLogbook as jest.Mock).mockReturnValue({
      mutate: mutateMock,
      isPending: true,
    });

    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    expect(screen.getByText('Generating PDF…')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /Generating PDF/i })
    ).toBeDisabled();
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeDisabled();
  });

  it('closes dialog on cancel click', async () => {
    const user = userEvent.setup();
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    await user.click(screen.getByRole('button', { name: /Cancel/i }));

    expect(onOpenChangeMock).toHaveBeenCalledWith(false);
  });

  it('has accessible activity type filter group', () => {
    render(<LogbookExportDialog open={true} onOpenChange={onOpenChangeMock} />);

    const filterGroup = screen.getByRole('group', {
      name: /Activity type filters/i,
    });
    expect(filterGroup).toBeInTheDocument();
  });
});
