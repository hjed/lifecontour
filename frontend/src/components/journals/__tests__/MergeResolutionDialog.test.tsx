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

    expect(mockOnResolve).toHaveBeenCalledWith(
      {
        title: 'Source Title',
        content: 'Target Content',
        type_data: {
          MOOD_RATING: { mood_value: 5 },
        },
      },
      'replace'
    );
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

      expect(mockOnResolve).toHaveBeenCalledWith(
        {
          type_data: {
            EVENT: { calendar_id: SOURCE_CAL_ID },
          },
        },
        'replace'
      );
    });
  });

  describe('event timing', () => {
    const CAL_ID = '11111111-1111-1111-1111-111111111111';

    /**
     * An event's timing is stored twice: `event_date_range` carries UTC
     * datetimes and the calendar row carries the clock times.
     */
    const makeTimedEvent = (
      id: string,
      range: { start: string; end: string },
      times: { start_time: string; end_time: string }
    ) =>
      ({
        id,
        type: 'journals',
        attributes: {
          title: 'Same Title',
          content: 'Same Content',
          event_date_range: range,
          created_at: '',
          updated_at: '',
          is_archived: false,
          journal_date: '',
          type_data: {
            event: { calendar_id: CAL_ID, is_all_day: false, ...times },
          },
        },
        relationships: {},
      }) as unknown as JournalResource;

    const targetEvent = () =>
      makeTimedEvent(
        '1',
        { start: '2026-08-23T09:00:00Z', end: '2026-08-23T10:00:00Z' },
        { start_time: '09:00:00', end_time: '10:00:00' }
      );

    const sourceEvent = () =>
      makeTimedEvent(
        '2',
        { start: '2026-08-23T19:30:00Z', end: '2026-08-23T22:00:00Z' },
        { start_time: '19:30:00', end_time: '22:00:00' }
      );

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

    it('asks about the event timing once, not three times', () => {
      renderDialog(targetEvent(), sourceEvent());

      expect(screen.getByText('Event Dates & Times')).toBeInTheDocument();
      expect(screen.queryByText('Event — Start Time')).not.toBeInTheDocument();
      expect(screen.queryByText('Event — End Time')).not.toBeInTheDocument();
      expect(screen.queryByText('19:30:00')).not.toBeInTheDocument();
      expect(screen.queryByText('22:00:00')).not.toBeInTheDocument();
    });

    it('sends the clock times of whichever side won the dates', async () => {
      const user = userEvent.setup();
      renderDialog(targetEvent(), sourceEvent());

      await user.click(screen.getByTestId('radio-source-event_date_range'));
      await user.click(
        screen.getByRole('button', { name: /resolve and merge/i })
      );

      expect(mockOnResolve).toHaveBeenCalledWith(
        {
          event_date_range: {
            start: '2026-08-23T19:30:00Z',
            end: '2026-08-23T22:00:00Z',
          },
          type_data: {
            event: { start_time: '19:30:00', end_time: '22:00:00' },
          },
        },
        'replace'
      );
    });

    it('keeps the target dates and target clock times together', async () => {
      const user = userEvent.setup();
      renderDialog(targetEvent(), sourceEvent());

      await user.click(
        screen.getByRole('button', { name: /resolve and merge/i })
      );

      expect(mockOnResolve).toHaveBeenCalledWith(
        {
          event_date_range: {
            start: '2026-08-23T09:00:00Z',
            end: '2026-08-23T10:00:00Z',
          },
          type_data: {
            event: { start_time: '09:00:00', end_time: '10:00:00' },
          },
        },
        'replace'
      );
    });

    it('still asks about a clock time that differs on its own', () => {
      const sameRange = {
        start: '2026-08-23T09:00:00Z',
        end: '2026-08-23T10:00:00Z',
      };
      renderDialog(
        makeTimedEvent('1', sameRange, {
          start_time: '09:00:00',
          end_time: '10:00:00',
        }),
        makeTimedEvent('2', sameRange, {
          start_time: '09:00:00',
          end_time: '11:00:00',
        })
      );

      expect(screen.queryByText('Event Dates & Times')).not.toBeInTheDocument();
      expect(screen.getByText('Event — End Time')).toBeInTheDocument();
    });
  });

  describe('fitness merge mode', () => {
    const makeFitnessJournal = (id: string, fitness: Record<string, unknown>) =>
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
          type_data: { fitness },
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

    const targetRide = () =>
      makeFitnessJournal('1', {
        distance: 5000,
        duration: 1800,
        calories: 300,
        strava_activity_id: '111',
      });

    const sourceRide = () =>
      makeFitnessJournal('2', {
        distance: 3000,
        duration: 1200,
        calories: 200,
        strava_activity_id: '222',
      });

    it('offers to combine the two activities and picks that by default', () => {
      renderDialog(targetRide(), sourceRide());

      expect(screen.getByTestId('radio-fitness-additive')).toBeChecked();
      expect(screen.getByTestId('radio-fitness-replace')).not.toBeChecked();
    });

    it('previews the combined totals', () => {
      renderDialog(targetRide(), sourceRide());

      const preview = screen.getByTestId('fitness-combined-preview');
      expect(preview).toHaveTextContent('8.00 km'); // 5000m + 3000m
      expect(preview).toHaveTextContent('50:00'); // 1800s + 1200s
      expect(preview).toHaveTextContent('500'); // 300 + 200 calories
    });

    it('previews every metric the merge will combine', () => {
      // A preview that omits a summed field would understate the result the
      // user is being asked to confirm.
      renderDialog(
        makeFitnessJournal('1', {
          distance: 5000,
          duration: 1800,
          elevation_gain: 50,
          elevation_loss: 40,
          calories: 300,
          heart_rate_avg: 140,
          heart_rate_max: 175,
        }),
        makeFitnessJournal('2', {
          distance: 3000,
          duration: 1200,
          elevation_gain: 30,
          elevation_loss: 25,
          calories: 200,
          heart_rate_avg: 160,
          heart_rate_max: 185,
        })
      );

      const preview = screen.getByTestId('fitness-combined-preview');
      expect(preview).toHaveTextContent('Elevation Gain80 m');
      expect(preview).toHaveTextContent('Elevation Loss65 m');
      expect(preview).toHaveTextContent('148 bpm'); // duration-weighted
      expect(preview).toHaveTextContent('185 bpm'); // the higher max
    });

    it('hides the per-field fitness conflicts while combining', () => {
      renderDialog(targetRide(), sourceRide());

      expect(
        screen.queryByTestId('radio-target-type_data.fitness.distance')
      ).not.toBeInTheDocument();
    });

    it('submits the additive mode without per-field fitness overrides', async () => {
      const user = userEvent.setup();
      renderDialog(targetRide(), sourceRide());

      await user.click(screen.getByRole('button', { name: /merge/i }));

      expect(mockOnResolve).toHaveBeenCalledWith({}, 'additive');
    });

    it('restores the per-field choices when combining is turned off', async () => {
      const user = userEvent.setup();
      renderDialog(targetRide(), sourceRide());

      await user.click(screen.getByTestId('radio-fitness-replace'));

      const distanceRadio = screen.getByTestId(
        'radio-target-type_data.fitness.distance'
      );
      expect(distanceRadio).toBeChecked();

      await user.click(
        screen.getByTestId('radio-source-type_data.fitness.distance')
      );
      await user.click(screen.getByRole('button', { name: /merge/i }));

      expect(mockOnResolve).toHaveBeenCalledWith(
        expect.objectContaining({
          type_data: expect.objectContaining({
            fitness: expect.objectContaining({ distance: 3000 }),
          }),
        }),
        'replace'
      );
    });

    it('honours a caller that pre-selects keeping one value per field', async () => {
      // A duplicate-review surface has already judged the two journals to be
      // the same activity, so confirming a match must not add them together.
      const user = userEvent.setup();
      render(
        <MergeResolutionDialog
          targetJournal={targetRide()}
          sourceJournal={sourceRide()}
          open={true}
          isPending={false}
          defaultFitnessMergeMode='replace'
          onOpenChange={mockOnOpenChange}
          onResolve={mockOnResolve}
        />
      );

      expect(screen.getByTestId('radio-fitness-replace')).toBeChecked();
      expect(
        screen.queryByTestId('fitness-combined-preview')
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /merge/i }));

      expect(mockOnResolve).toHaveBeenCalledWith(expect.anything(), 'replace');
    });

    it('weights the average heart rate by a recorded zero duration', () => {
      // A zero-length part contributes its heart rate but no weight — and two
      // zero-length parts must not divide by zero.
      renderDialog(
        makeFitnessJournal('1', { heart_rate_avg: 100, duration: 0 }),
        makeFitnessJournal('2', { heart_rate_avg: 160, duration: 1200 })
      );

      expect(screen.getByTestId('fitness-combined-preview')).toHaveTextContent(
        '160 bpm'
      );
    });

    it('says both Strava activities stay linked', () => {
      renderDialog(targetRide(), sourceRide());

      expect(screen.getByText(/both strava activities/i)).toBeInTheDocument();
    });

    it('is not offered when only one journal has fitness data', () => {
      renderDialog(targetRide(), mockSource);

      expect(
        screen.queryByTestId('radio-fitness-additive')
      ).not.toBeInTheDocument();
    });
  });
});
