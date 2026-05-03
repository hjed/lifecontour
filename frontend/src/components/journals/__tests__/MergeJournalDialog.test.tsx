import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MergeJournalDialog } from '../MergeJournalDialog';
import { useMergeJournal } from '@/lib/api/journals';

// Mock dependencies
jest.mock('@/lib/api/journals', () => ({
  useMergeJournal: jest.fn(),
  useSearchJournals: jest.fn(), // If needed by children
  useJournal: jest.fn(),
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

    // Mock useJournal to avoid 'is not a function' TypeError
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useJournal } = require('@/lib/api/journals');
    useJournal.mockImplementation((id: string) => {
      if (!id) return { data: { data: null }, isPending: false };
      return {
        data: {
          data: {
            id,
            attributes: { title: id === 'target-456' ? 'Target' : 'Source' },
          },
        },
        isPending: false,
      };
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
      name: /Next/i,
    });
    expect(mergeBtn).toBeDisabled();

    // Select a journal
    await user.click(screen.getByTestId('select-mock-journal'));

    // Should show selected journal name
    expect(screen.getByText(/Mock Source Journal/i)).toBeInTheDocument();

    // Merge button should now be enabled
    expect(mergeBtn).not.toBeDisabled();
  });

  it('opens resolution dialog when Next is clicked', async () => {
    const user = userEvent.setup();
    render(<MergeJournalDialog targetJournalId={targetJournalId} />);

    await user.click(screen.getByRole('button', { name: /Merge journal/i }));
    await user.click(screen.getByTestId('select-mock-journal'));

    const nextBtn = screen.getByRole('button', {
      name: /Next/i,
    });
    await user.click(nextBtn);

    // The resolution dialog should be opened (indicated by its title)
    expect(
      await screen.findByText(/Resolve Merge Conflicts/i)
    ).toBeInTheDocument();
  });

  it('calls onOpenChange(false) after successful merge when externally controlled', async () => {
    const user = userEvent.setup();
    const onOpenChangeMock = jest.fn();

    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { useJournal } = require('@/lib/api/journals');
    // Return journals with identical attributes (no conflicts)
    useJournal.mockImplementation((id: string) => {
      if (!id) return { data: null, isPending: false };
      return {
        data: {
          data: {
            id,
            type: 'journals',
            attributes: {
              title: 'Same Title',
              content: 'Same Content',
              event_date_range: null,
              types: ['note'],
              contacts: [],
              tags: [],
              type_data: {},
            },
          },
        },
        isPending: false,
      };
    });

    render(
      <MergeJournalDialog
        targetJournalId={targetJournalId}
        sourceJournalId='source-123'
        open={true}
        onOpenChange={onOpenChangeMock}
      />
    );

    // Wait for the resolution dialog to auto-open (since sourceJournalId is pre-populated)
    const mergeBtn = await screen.findByRole('button', { name: /Merge/i });

    await user.click(mergeBtn);

    // The mutateAsync should have been called
    expect(mutateAsyncMock).toHaveBeenCalled();

    // onOpenChange should be called with false to notify the parent
    expect(onOpenChangeMock).toHaveBeenCalledWith(false);
  });
});
