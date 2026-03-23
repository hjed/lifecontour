import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MergeResolutionDialog } from '../MergeResolutionDialog';
import { JournalResource } from '@/types/journals';

describe('MergeResolutionDialog', () => {
  const mockTarget = {
    id: '1',
    type: 'journals',
    attributes: {
      title: 'Target Title',
      content: 'Target Content',
      event_date_range: undefined,
      created_at: '',
      updated_at: '',
      is_archived: false,
      journal_date: '',
      type_data: {
        MOOD_RATING: { mood_value: 5, energy_level: 5 },
      },
    },
    relationships: {},
  } as unknown as JournalResource;

  const mockSource = {
    id: '2',
    type: 'journals',
    attributes: {
      title: 'Source Title',
      content: 'Source Content',
      event_date_range: undefined,
      created_at: '',
      updated_at: '',
      is_archived: false,
      journal_date: '',
      type_data: {
        MOOD_RATING: { mood_value: 8, energy_level: 5 },
      },
    },
    relationships: {},
  } as unknown as JournalResource;

  const mockOnResolve = jest.fn();
  const mockOnOpenChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders conflicts correctly', () => {
    render(
      <MergeResolutionDialog
        targetJournal={mockTarget}
        sourceJournal={mockSource}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // Should render dialog title
    expect(screen.getByText('Resolve Merge Conflicts')).toBeInTheDocument();

    // Should list Title and Content and MOOD_RATING conflicts
    expect(screen.getByText('Title')).toBeInTheDocument();
    expect(screen.getByText('Content')).toBeInTheDocument();
    expect(screen.getByText('MOOD_RATING - mood_value')).toBeInTheDocument();

    // Should show target and source values
    expect(screen.getByText('Target Title')).toBeInTheDocument();
    expect(screen.getByText('Source Title')).toBeInTheDocument();
    expect(screen.getByText('Target Content')).toBeInTheDocument();
    expect(screen.getByText('Source Content')).toBeInTheDocument();
    // MOOD_RATING values (5 and 8)
    expect(screen.getAllByText('5').length).toBeGreaterThan(0);
    expect(screen.getByText('8')).toBeInTheDocument();

    // Should default to target values
    const targetTitleRadio = screen.getByTestId('radio-target-title');
    expect(targetTitleRadio).toBeChecked();
  });

  it('submits selected overrides', async () => {
    const user = userEvent.setup();
    render(
      <MergeResolutionDialog
        targetJournal={mockTarget}
        sourceJournal={mockSource}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // Change title to Source
    const titleSourceRadio = screen.getByTestId('radio-source-title');
    await user.click(titleSourceRadio);

    await user.click(
      screen.getByRole('button', { name: /resolve and merge/i })
    );

    expect(mockOnResolve).toHaveBeenCalledWith({
      title: 'Source Title',
      content: 'Target Content',
      type_data: {
        MOOD_RATING: { mood_value: 5 },
      },
    });
  });

  it('renders No Conflicts message if there are no conflicts', () => {
    const cloneTarget = JSON.parse(JSON.stringify(mockTarget));
    render(
      <MergeResolutionDialog
        targetJournal={cloneTarget}
        sourceJournal={cloneTarget}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    expect(screen.getByText('Confirm Merge')).toBeInTheDocument();
    expect(screen.getByText(/No conflicts detected/i)).toBeInTheDocument();
  });
});
