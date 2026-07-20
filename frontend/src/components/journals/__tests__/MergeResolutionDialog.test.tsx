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
    expect(screen.getByText('Mood Rating — Mood Value')).toBeInTheDocument();

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

  describe('calendar conflicts', () => {
    const TARGET_CAL_ID = '11111111-1111-1111-1111-111111111111';
    const SOURCE_CAL_ID = '22222222-2222-2222-2222-222222222222';

    const makeEventJournal = (
      id: string,
      calendarId: string,
      calendar: { id: string; name: string } | null
    ) =>
      ({
        id,
        type: 'journals',
        attributes: {
          title: 'Same Title',
          content: 'Same Content',
          event_date_range: undefined,
          created_at: '',
          updated_at: '',
          is_archived: false,
          journal_date: '',
          calendar,
          type_data: {
            EVENT: { calendar_id: calendarId, is_all_day: false },
          },
        },
        relationships: {},
      }) as unknown as JournalResource;

    const renderDialog = (target: JournalResource, source: JournalResource) =>
      render(
        <MergeResolutionDialog
          targetJournal={target}
          sourceJournal={source}
          open={true}
          isPending={false}
          onOpenChange={mockOnOpenChange}
          onResolve={mockOnResolve}
        />
      );

    it('shows calendar names instead of raw ids', () => {
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, {
          id: TARGET_CAL_ID,
          name: 'Work Calendar',
        }),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      expect(screen.getByText('Work Calendar')).toBeInTheDocument();
      expect(screen.getByText('Personal Calendar')).toBeInTheDocument();
      expect(screen.queryByText(TARGET_CAL_ID)).not.toBeInTheDocument();
      expect(screen.queryByText(SOURCE_CAL_ID)).not.toBeInTheDocument();
    });

    it('falls back to the raw id when no calendar is embedded', () => {
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, null),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      expect(screen.getByText(TARGET_CAL_ID)).toBeInTheDocument();
      expect(screen.getByText('Personal Calendar')).toBeInTheDocument();
    });

    it('falls back to the raw id when the embedded calendar does not match', () => {
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, {
          id: 'some-other-calendar',
          name: 'Stale Calendar',
        }),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      expect(screen.getByText(TARGET_CAL_ID)).toBeInTheDocument();
      expect(screen.queryByText('Stale Calendar')).not.toBeInTheDocument();
    });

    it('labels the conflict in human-readable text', () => {
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, {
          id: TARGET_CAL_ID,
          name: 'Work Calendar',
        }),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      expect(screen.getByText('Event — Calendar')).toBeInTheDocument();
      expect(screen.queryByText('EVENT - calendar_id')).not.toBeInTheDocument();
    });

    it('does not offer a custom free-text value for a calendar', () => {
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, {
          id: TARGET_CAL_ID,
          name: 'Work Calendar',
        }),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      expect(
        screen.queryByTestId('radio-custom-type_data.EVENT.calendar_id')
      ).not.toBeInTheDocument();
    });

    it('still submits the raw calendar id, not the display name', async () => {
      const user = userEvent.setup();
      renderDialog(
        makeEventJournal('1', TARGET_CAL_ID, {
          id: TARGET_CAL_ID,
          name: 'Work Calendar',
        }),
        makeEventJournal('2', SOURCE_CAL_ID, {
          id: SOURCE_CAL_ID,
          name: 'Personal Calendar',
        })
      );

      await user.click(
        screen.getByTestId('radio-source-type_data.EVENT.calendar_id')
      );
      await user.click(
        screen.getByRole('button', { name: /resolve and merge/i })
      );

      expect(mockOnResolve).toHaveBeenCalledWith({
        type_data: {
          EVENT: { calendar_id: SOURCE_CAL_ID },
        },
      });
    });
  });
});
