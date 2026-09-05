/**
 * @jest-environment jsdom
 *
 * The tomorrow disclosure (**W19**, **W20**).
 *
 * The specification asks for tomorrow "beneath today, collapsed by default,
 * expandable in place... the same information in the same form", so these
 * tests are about four things and nothing else: that it is shut when it
 * arrives, that it says what is behind it before you open it, that opening it
 * draws today's own row component over tomorrow's entries, and that all of
 * that is available to someone who never sees the chevron.
 *
 * The component is a pure function of `agenda.tomorrow`, so every case is a
 * fixture rather than a query — the card's own tests cover the wiring.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TomorrowDisclosure } from '../TomorrowDisclosure';
import type {
  HomeDashboardAgendaDay,
  HomeDashboardAgendaEntry,
} from '@/lib/api/home-dashboard';

/** 2026-08-01 is a Saturday, which is what the label has to work out. */
const TOMORROW = '2026-08-01';

const TOMORROW_LIST_NAME = "Tomorrow's agenda";
const TOMORROW_EMPTY_LINE = 'Nothing scheduled tomorrow.';

function entry(
  overrides: Partial<HomeDashboardAgendaEntry> & { journal_id: number }
): HomeDashboardAgendaEntry {
  return {
    title: `Event ${overrides.journal_id}`,
    is_all_day: false,
    starts_at: '2026-08-01T09:00:00+10:00',
    ends_at: '2026-08-01T10:00:00+10:00',
    start_time: '09:00:00',
    end_time: '10:00:00',
    timezone: 'Australia/Sydney',
    location: null,
    calendar_color: '#336699',
    is_cancelled: false,
    tags: [],
    participants: [],
    ...overrides,
  };
}

/** The server's order: all-day first, then timed ascending. */
const HOLIDAY = entry({
  journal_id: 11,
  title: 'Bank holiday',
  is_all_day: true,
  start_time: null,
  end_time: null,
});
const STANDUP = entry({
  journal_id: 12,
  title: 'Tomorrow standup',
  start_time: '09:00:00',
  end_time: '09:15:00',
});
const RETRO = entry({
  journal_id: 13,
  title: 'Tomorrow retro',
  start_time: '16:00:00',
  end_time: '17:00:00',
  is_cancelled: true,
});

function day(entries: HomeDashboardAgendaEntry[]): HomeDashboardAgendaDay {
  return { date: TOMORROW, entries };
}

function trigger() {
  return screen.getByRole('button', { name: /tomorrow/i });
}

describe('TomorrowDisclosure', () => {
  describe('collapsed, which is how it arrives (W19)', () => {
    it('reports itself shut and draws none of tomorrow’s entries', () => {
      render(<TomorrowDisclosure day={day([STANDUP, RETRO])} />);

      expect(trigger()).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('Tomorrow standup')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('list', { name: TOMORROW_LIST_NAME })
      ).not.toBeInTheDocument();
    });

    it('labels itself from the day the server sent, not a date worked out here', () => {
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      expect(screen.getByTestId('tomorrow-label')).toHaveTextContent(
        'Tomorrow — Saturday, 1 August'
      );
    });

    it('counts what is behind it, cancelled entries included', () => {
      render(<TomorrowDisclosure day={day([HOLIDAY, STANDUP, RETRO])} />);

      expect(screen.getByTestId('tomorrow-count')).toHaveTextContent(
        '3 events'
      );
    });

    it('writes the singular for a single event', () => {
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      expect(screen.getByTestId('tomorrow-count')).toHaveTextContent('1 event');
    });

    it('points its chevron right', () => {
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      expect(screen.getByTestId('tomorrow-chevron-closed')).toBeInTheDocument();
      expect(
        screen.queryByTestId('tomorrow-chevron-open')
      ).not.toBeInTheDocument();
    });

    /**
     * What a screen-reader user hears tabbing onto it. "Tomorrow" alone would
     * make them open it to learn whether it was worth opening.
     */
    it('names the day and the count in its accessible name', () => {
      render(<TomorrowDisclosure day={day([HOLIDAY, STANDUP])} />);

      expect(
        screen.getByRole('button', {
          name: 'Tomorrow — Saturday, 1 August, 2 events',
        })
      ).toBeInTheDocument();
    });
  });

  describe('expanding it (W20)', () => {
    it('reveals tomorrow’s entries in the order the payload sent them', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([HOLIDAY, STANDUP, RETRO])} />);

      await user.click(trigger());

      const rows = within(
        screen.getByRole('list', { name: TOMORROW_LIST_NAME })
      ).getAllByRole('listitem');
      expect(rows.map(row => row.getAttribute('data-testid'))).toEqual([
        'agenda-entry-11',
        'agenda-entry-12',
        'agenda-entry-13',
      ]);
    });

    /**
     * "The same information in the same form" — the specification's words, and
     * the reason this is the very same `AgendaEntryRow` today's list uses
     * rather than a second row that could drift from it.
     */
    it('draws them through the agenda row, in the W12–W18 form', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([HOLIDAY, STANDUP, RETRO])} />);

      await user.click(trigger());

      const holiday = screen.getByTestId('agenda-entry-11');
      expect(
        within(holiday).getByTestId('agenda-entry-all-day')
      ).toBeInTheDocument();

      const standup = screen.getByTestId('agenda-entry-12');
      expect(
        within(standup).getByTestId('agenda-entry-time')
      ).toHaveTextContent('09:00 – 09:15');
      expect(
        within(standup).getByRole('link', { name: 'Tomorrow standup' })
      ).toHaveAttribute('href', '/journals/12');

      const retro = screen.getByTestId('agenda-entry-13');
      expect(
        within(retro).getByTestId('agenda-entry-cancelled')
      ).toBeInTheDocument();
    });

    it('turns its chevron down and reports itself open', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      await user.click(trigger());

      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByTestId('tomorrow-chevron-open')).toBeInTheDocument();
      expect(
        screen.queryByTestId('tomorrow-chevron-closed')
      ).not.toBeInTheDocument();
    });

    it('shuts again when the trigger is pressed a second time', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      await user.click(trigger());
      expect(screen.getByText('Tomorrow standup')).toBeInTheDocument();

      await user.click(trigger());

      expect(trigger()).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('Tomorrow standup')).not.toBeInTheDocument();
    });
  });

  /**
   * The disclosure is a real `button` inside a Radix `Collapsible`, so keyboard
   * operation is structural rather than handler-driven. These pin it anyway:
   * the wireframe's row is the only way to reach tomorrow, and a mouse-only
   * one would put the whole feature behind a pointer.
   */
  describe('operated from the keyboard', () => {
    it('is reachable by Tab and opens on Enter', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      await user.tab();
      expect(trigger()).toHaveFocus();

      await user.keyboard('{Enter}');

      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
      expect(screen.getByText('Tomorrow standup')).toBeInTheDocument();
    });

    it('opens on Space as well', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      await user.tab();
      await user.keyboard(' ');

      expect(trigger()).toHaveAttribute('aria-expanded', 'true');
    });
  });

  describe('exposed to assistive technology', () => {
    it('controls the region it opens, and that region is named by the trigger', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      await user.click(trigger());

      const controls = trigger().getAttribute('aria-controls');
      expect(controls).toBeTruthy();
      const region = screen.getByRole('region', {
        name: 'Tomorrow — Saturday, 1 August, 1 event',
      });
      expect(region).toHaveAttribute('id', controls);
    });

    /**
     * Radix leaves the panel in the DOM but `hidden` while shut, and omits
     * `aria-controls` until it opens — a region nobody can reach is not one
     * the button meaningfully controls. Writing the attribute here anyway
     * (as this component first did) overrode that decision for no gain, so
     * this pins it: shut, the panel is out of the accessibility tree and the
     * trigger claims to control nothing.
     */
    it('claims to control nothing while the panel is hidden', () => {
      render(<TomorrowDisclosure day={day([STANDUP])} />);

      expect(screen.getByTestId('tomorrow-panel')).not.toBeVisible();
      expect(trigger()).not.toHaveAttribute('aria-controls');
    });

    it('hides its chevron from the accessibility tree', () => {
      const { container } = render(<TomorrowDisclosure day={day([STANDUP])} />);

      const icons = container.querySelectorAll('svg');
      expect(icons.length).toBeGreaterThan(0);
      icons.forEach(icon => {
        expect(icon).toHaveAttribute('aria-hidden', 'true');
      });
    });
  });

  /**
   * A clear day tomorrow is a real answer, and hiding the control would make
   * it indistinguishable from a dashboard that never had a tomorrow at all.
   */
  describe('with nothing scheduled tomorrow', () => {
    it('keeps the row, counting none', () => {
      render(<TomorrowDisclosure day={day([])} />);

      expect(trigger()).toBeInTheDocument();
      expect(screen.getByTestId('tomorrow-count')).toHaveTextContent(
        '0 events'
      );
    });

    it('says so in one line when opened, with no rows and no error', async () => {
      const user = userEvent.setup();
      render(<TomorrowDisclosure day={day([])} />);

      await user.click(trigger());

      expect(screen.getByText(TOMORROW_EMPTY_LINE)).toBeInTheDocument();
      expect(screen.queryAllByRole('listitem')).toHaveLength(0);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
