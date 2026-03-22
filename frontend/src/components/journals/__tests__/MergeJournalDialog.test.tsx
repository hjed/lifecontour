import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MergeJournalDialog } from '../MergeJournalDialog';
import { useMergeJournal } from '@/lib/api/journals';

// Mock dependencies
jest.mock('@/lib/api/journals', () => ({
  useMergeJournal: jest.fn(),
  useSearchJournals: jest.fn(), // If needed by children
}));

// Mock the combobox to simplify testing the dialog state machine
jest.mock('../JournalSearchCombobox', () => ({
  JournalSearchCombobox: ({ onSelect, excludeJournalId }: any) => (
    <div data-testid='mock-combobox'>
      <span data-testid='exclude-id'>{excludeJournalId}</span>
      <button
        type='button'
        data-testid='select-mock-journal'
        onClick={() =>
          onSelect({
            id: 'source-123',
            attributes: { title: 'Mock Source Journal' },
          })
        }
      >
        Select Source Journal
      </button>
    </div>
  ),
}));

describe('MergeJournalDialog', () => {
  const targetJournalId = 'target-456';
  let mutateAsyncMock: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    mutateAsyncMock = jest.fn().mockResolvedValue({ data: {} });

    (useMergeJournal as jest.Mock).mockReturnValue({
      mutateAsync: mutateAsyncMock,
      isPending: false,
    });
  });

  it('renders merge button and opens dialog on click', async () => {
    const user = userEvent.setup();
    render(<MergeJournalDialog targetJournalId={targetJournalId} />);

    // Trigger button should be visible
    const trigger = screen.getByRole('button', { name: /Merge journal/i });
    expect(trigger).toBeInTheDocument();

    // Click trigger to open dialog
    await user.click(trigger);

    // Dialog contents should appear
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Merge Another Journal')).toBeInTheDocument();

    // Combobox should be present with correct exclude ID
    expect(screen.getByTestId('mock-combobox')).toBeInTheDocument();
    expect(screen.getByTestId('exclude-id')).toHaveTextContent(targetJournalId);
  });

  it('disables merge button until a source journal is selected', async () => {
    const user = userEvent.setup();
    render(<MergeJournalDialog targetJournalId={targetJournalId} />);

    await user.click(screen.getByRole('button', { name: /Merge journal/i }));

    const mergeBtn = screen.getByRole('button', {
      name: /Merge and Delete Source/i,
    });
    expect(mergeBtn).toBeDisabled();

    // Select a journal
    await user.click(screen.getByTestId('select-mock-journal'));

    // Should show selected journal name
    expect(screen.getByText(/Mock Source Journal/i)).toBeInTheDocument();

    // Merge button should now be enabled
    expect(mergeBtn).not.toBeDisabled();
  });

  it('calls merge api and closes dialog on successful merge', async () => {
    const user = userEvent.setup();
    render(<MergeJournalDialog targetJournalId={targetJournalId} />);

    await user.click(screen.getByRole('button', { name: /Merge journal/i }));
    await user.click(screen.getByTestId('select-mock-journal'));

    const mergeBtn = screen.getByRole('button', {
      name: /Merge and Delete Source/i,
    });
    await user.click(mergeBtn);

    expect(mutateAsyncMock).toHaveBeenCalledWith({
      targetId: targetJournalId,
      sourceId: 'source-123',
    });

    // Dialog should be closed
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('shows pending state when merging', async () => {
    (useMergeJournal as jest.Mock).mockReturnValue({
      mutateAsync: mutateAsyncMock,
      isPending: true,
    });

    const user = userEvent.setup();
    render(<MergeJournalDialog targetJournalId={targetJournalId} />);

    await user.click(screen.getByRole('button', { name: /Merge journal/i }));
    await user.click(screen.getByTestId('select-mock-journal'));

    const mergeBtn = screen.getByRole('button', { name: /Merging.../i });
    expect(mergeBtn).toBeInTheDocument();
    expect(mergeBtn).toBeDisabled();
  });
});
