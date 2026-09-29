import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MergeSeriesDialog } from '../MergeSeriesDialog';
import {
  DEFAULT_SERIES_MERGE_POLICIES,
  JournalApiError,
  useJournalSeries,
  useMergeSeries,
  useSeriesMergePreview,
} from '@/lib/api/journals';
import type { SeriesMergePlan } from '@/types/journals';

jest.mock('@/lib/api/journals', () => {
  const actual = jest.requireActual('@/lib/api/journals');
  return {
    DEFAULT_SERIES_MERGE_POLICIES: actual.DEFAULT_SERIES_MERGE_POLICIES,
    JournalApiError: actual.JournalApiError,
    useJournalSeries: jest.fn(),
    useMergeSeries: jest.fn(),
    useSeriesMergePreview: jest.fn(),
  };
});

// Radix Select does not open in jsdom; a native select exercises the same
// onValueChange contract.
jest.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children?: React.ReactNode;
    onValueChange?: (value: string) => void;
    value?: string;
  }) => (
    <select
      aria-label='Series to merge in'
      value={value ?? ''}
      onChange={event => onValueChange?.(event.target.value)}
    >
      <option value=''>Choose</option>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
  SelectItem: ({
    children,
    value,
  }: {
    children?: React.ReactNode;
    value: string;
  }) => <option value={value}>{children}</option>,
}));

const PLAN: SeriesMergePlan = {
  source_series_id: 'old',
  destination_series_id: 'dest',
  days: [
    {
      date: '2026-08-03',
      kind: 'candidate',
      source_journal_ids: [1],
      destination_journal_ids: [2],
      differing_fields: ['title'],
      skip_reason: null,
    },
    {
      date: '2026-08-10',
      kind: 'candidate',
      source_journal_ids: [3],
      destination_journal_ids: [4],
      differing_fields: [],
      skip_reason: null,
    },
    {
      date: '2026-08-17',
      kind: 'skipped',
      source_journal_ids: [5],
      destination_journal_ids: [6],
      differing_fields: ['location'],
      skip_reason: 'location',
    },
    {
      date: '2026-08-24',
      kind: 'unpaired',
      source_journal_ids: [7],
      destination_journal_ids: [],
      differing_fields: [],
      skip_reason: null,
    },
  ],
  journals: Object.fromEntries(
    [1, 2, 3, 4, 5, 6, 7].map(id => [
      String(id),
      {
        id,
        title: id % 2 ? `Old ${id}` : `New ${id}`,
        event_date_range_start: '2026-08-03T09:00:00Z',
      },
    ])
  ),
};

describe('MergeSeriesDialog', () => {
  let mutateAsync: jest.Mock;
  let refetch: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    mutateAsync = jest.fn().mockResolvedValue(PLAN);
    refetch = jest.fn();
    (useJournalSeries as jest.Mock).mockReturnValue({
      data: {
        data: [
          { id: 'dest', name: 'Standup' },
          { id: 'old', name: 'Old standup' },
        ],
      },
    });
    (useMergeSeries as jest.Mock).mockReturnValue({
      mutateAsync,
      isPending: false,
    });
    (useSeriesMergePreview as jest.Mock).mockImplementation(
      (_dest: string, source: string | null) => ({
        data: source ? PLAN : undefined,
        isFetching: false,
        error: null,
        refetch,
      })
    );
  });

  async function openAndChooseSource() {
    const user = userEvent.setup();
    render(
      <MergeSeriesDialog
        destinationSeriesId='dest'
        destinationSeriesName='Standup'
      />
    );
    await user.click(screen.getByRole('button', { name: /merge a series/i }));
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Series to merge in' }),
      'old'
    );
    return user;
  }

  it('offers every other series as the source', async () => {
    const user = userEvent.setup();
    render(
      <MergeSeriesDialog
        destinationSeriesId='dest'
        destinationSeriesName='Standup'
      />
    );

    await user.click(screen.getByRole('button', { name: /merge a series/i }));

    const select = screen.getByRole('combobox', { name: 'Series to merge in' });
    expect(
      within(select).getByRole('option', { name: 'Old standup' })
    ).toBeInTheDocument();
    expect(
      within(select).queryByRole('option', { name: 'Standup' })
    ).not.toBeInTheDocument();
  });

  it('shows each day of the preview with its outcome', async () => {
    await openAndChooseSource();

    const rows = screen.getAllByTestId(/^series-merge-day-/);
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('Old 1');
    expect(rows[0]).toHaveTextContent('New 2');
    expect(rows[0]).toHaveTextContent(/title differs/i);
    expect(rows[2]).toHaveTextContent(/not merged: location differs/i);
    expect(rows[3]).toHaveTextContent(/moves into this series/i);
    expect(
      within(rows[0]).getByRole('checkbox', { name: /merge 3 aug/i })
    ).toBeChecked();
    expect(within(rows[2]).queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('re-previews with the chosen field policy', async () => {
    const user = await openAndChooseSource();

    await user.click(
      within(screen.getByRole('radiogroup', { name: 'Title' })).getByRole(
        'radio',
        { name: 'Skip if different' }
      )
    );

    expect(useSeriesMergePreview).toHaveBeenLastCalledWith('dest', 'old', {
      ...DEFAULT_SERIES_MERGE_POLICIES,
      title: 'skip_if_different',
    });
  });

  it('offers combine for content only', async () => {
    await openAndChooseSource();

    expect(
      within(screen.getByRole('radiogroup', { name: 'Content' })).getByRole(
        'radio',
        { name: 'Combine' }
      )
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('radiogroup', { name: 'Title' })).queryByRole(
        'radio',
        { name: 'Combine' }
      )
    ).not.toBeInTheDocument();
  });

  it('merges only the ticked pairs', async () => {
    const user = await openAndChooseSource();

    await user.click(screen.getByRole('checkbox', { name: /merge 10 aug/i }));
    await user.click(screen.getByRole('button', { name: /^merge series$/i }));

    expect(mutateAsync).toHaveBeenCalledWith({
      destinationSeriesId: 'dest',
      sourceSeriesId: 'old',
      policies: DEFAULT_SERIES_MERGE_POLICIES,
      pairs: [{ source_journal_id: 1, destination_journal_id: 2 }],
    });
  });

  it('previews again when the series changed since the preview', async () => {
    mutateAsync.mockRejectedValue(new JournalApiError('changed', 409));
    const user = await openAndChooseSource();

    await user.click(screen.getByRole('button', { name: /^merge series$/i }));

    expect(refetch).toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
