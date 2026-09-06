/**
 * @jest-environment jsdom
 *
 * The zone a *new* event records.
 *
 * It has to be the user's configured one, because that is what the date range
 * submitted alongside it will be anchored in — and the two disagreeing is what
 * puts an event on the wrong calendar day for everything that reads its bounds
 * back through `journal_calendar_info.timezone` (#1401).
 *
 * The awkward part is timing: the settings read may not have landed when this
 * editor mounts, so the first render can only guess, and the guess is state the
 * parent form has already been told about.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventTypeEditor } from '@/components/journals/type-editors/EventTypeEditor';
import { useUserTimezone } from '@/lib/api/settings';

jest.mock('@/lib/api/settings', () => ({
  useUserTimezone: jest.fn(),
}));

jest.mock('@/lib/api/journals', () => ({
  useCalendars: () => ({
    data: {
      data: [
        {
          id: 'calendar-uuid-123',
          attributes: { name: 'Test Calendar', color: '#ff0000' },
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
}));

const mockUseUserTimezone = useUserTimezone as jest.Mock;

describe('EventTypeEditor timezone seeding', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('reports the configured zone to the parent form', () => {
    mockUseUserTimezone.mockReturnValue('Australia/Sydney');
    const onChange = jest.fn();

    render(<EventTypeEditor createMode onChange={onChange} />);

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ timezone: 'Australia/Sydney' })
    );
  });

  it('follows the configured zone when the settings read lands late', () => {
    // The first render happens before the settings query resolves, so all the
    // editor has is the browser/cache fallback — and it has already told the
    // parent form about it.
    mockUseUserTimezone.mockReturnValue('America/New_York');
    const onChange = jest.fn();
    const { rerender } = render(
      <EventTypeEditor createMode onChange={onChange} />
    );

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ timezone: 'America/New_York' })
    );

    // ...and now the user's real zone arrives.
    mockUseUserTimezone.mockReturnValue('Australia/Sydney');
    rerender(<EventTypeEditor createMode onChange={onChange} />);

    expect(screen.getByLabelText(/timezone/i)).toHaveValue('Australia/Sydney');
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ timezone: 'Australia/Sydney' })
    );
  });

  it('leaves a zone the user typed alone', async () => {
    const user = userEvent.setup();
    mockUseUserTimezone.mockReturnValue('America/New_York');
    const onChange = jest.fn();
    const { rerender } = render(
      <EventTypeEditor createMode onChange={onChange} />
    );

    const timezoneInput = screen.getByLabelText(/timezone/i);
    await user.clear(timezoneInput);
    await user.type(timezoneInput, 'America/Los_Angeles');

    // The settings read lands afterwards. A deliberate choice outranks it.
    mockUseUserTimezone.mockReturnValue('Australia/Sydney');
    rerender(<EventTypeEditor createMode onChange={onChange} />);

    expect(screen.getByLabelText(/timezone/i)).toHaveValue(
      'America/Los_Angeles'
    );
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ timezone: 'America/Los_Angeles' })
    );
  });

  it('does not touch the zone of an event that already has one', () => {
    mockUseUserTimezone.mockReturnValue('Australia/Sydney');
    const onChange = jest.fn();

    render(
      <EventTypeEditor
        createMode
        data={{
          calendar_id: 'calendar-uuid-123',
          is_all_day: false,
          sync_invitees: false,
          private_description: false,
          description: '',
          timezone: 'America/Los_Angeles',
        }}
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText(/timezone/i)).toHaveValue(
      'America/Los_Angeles'
    );
  });
});
