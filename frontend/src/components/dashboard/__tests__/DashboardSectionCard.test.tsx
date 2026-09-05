/**
 * @jest-environment jsdom
 *
 * The shared card shell behind the three evidence sections, and specifically
 * **when it decides it is empty**.
 *
 * That decision is the seam every later section phase lands on: Phases 7, 12,
 * 14 and 15 will each pass `entries.map(...)`, which is an **empty array** when
 * the window holds nothing — a *ready* section with no rows, which is exactly
 * the state **W29** and the wireframe's gaps 1 and 2 ask for a quiet line in.
 * An emptiness test that only catches "no children at all" would leave those
 * sections drawing a blank card instead.
 */

import { render, screen } from '@testing-library/react';
import { CalendarCheck, CalendarDays } from 'lucide-react';
import { DashboardSectionCard } from '../DashboardSectionCard';

const CARD_PROPS = {
  icon: CalendarDays,
  iconChipClassName: 'bg-chart-1 text-white',
  title: 'Agenda',
  description: "Today's schedule in time order, all-day items first.",
  listLabel: "Today's agenda",
  emptyIcon: CalendarCheck,
  emptyMessage: 'Nothing scheduled today.',
} as const;

describe('DashboardSectionCard', () => {
  describe('when it holds no entries', () => {
    it('shows its empty line when given no children at all', () => {
      render(<DashboardSectionCard {...CARD_PROPS} />);

      expect(screen.getByText('Nothing scheduled today.')).toBeInTheDocument();
    });

    /**
     * The case a truthiness check gets wrong: `[]` is truthy, so `!children`
     * is `false` and the empty line would be suppressed on a section that
     * genuinely has nothing to show.
     */
    it('shows its empty line when a section maps over an empty list', () => {
      const entries: string[] = [];

      render(
        <DashboardSectionCard {...CARD_PROPS}>
          {entries.map(entry => (
            <li key={entry}>{entry}</li>
          ))}
        </DashboardSectionCard>
      );

      expect(screen.getByText('Nothing scheduled today.')).toBeInTheDocument();
      expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    });

    it('keeps the labelled list present so assistive tech still finds it', () => {
      render(<DashboardSectionCard {...CARD_PROPS} />);

      expect(
        screen.getByRole('list', { name: "Today's agenda" })
      ).toBeInTheDocument();
    });
  });

  /**
   * A section that has not answered yet, or answered `unavailable`, holds no
   * entries either — but "nothing scheduled" would be a false claim about it.
   * The placeholder is what a card shows *instead of* the empty line in those
   * cases, so the three states cannot be confused.
   */
  describe('when given a placeholder', () => {
    it('renders the placeholder in place of the empty line', () => {
      render(
        <DashboardSectionCard
          {...CARD_PROPS}
          placeholder={<p>Loading today&apos;s agenda...</p>}
        />
      );

      expect(screen.getByText("Loading today's agenda...")).toBeInTheDocument();
      expect(
        screen.queryByText('Nothing scheduled today.')
      ).not.toBeInTheDocument();
    });

    it('still keeps the labelled list present', () => {
      render(
        <DashboardSectionCard {...CARD_PROPS} placeholder={<p>Loading</p>} />
      );

      expect(
        screen.getByRole('list', { name: "Today's agenda" })
      ).toBeInTheDocument();
      expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    });

    it('is ignored once the section holds entries', () => {
      render(
        <DashboardSectionCard {...CARD_PROPS} placeholder={<p>Loading</p>}>
          <li>Standup</li>
        </DashboardSectionCard>
      );

      expect(screen.getByRole('listitem')).toHaveTextContent('Standup');
      expect(screen.queryByText('Loading')).not.toBeInTheDocument();
    });
  });

  describe('when it holds entries', () => {
    it('renders them in the labelled list and drops the empty line', () => {
      const entries = ['Standup', 'Lunch with Sam'];

      render(
        <DashboardSectionCard {...CARD_PROPS}>
          {entries.map(entry => (
            <li key={entry}>{entry}</li>
          ))}
        </DashboardSectionCard>
      );

      const list = screen.getByRole('list', { name: "Today's agenda" });
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
      expect(list).toHaveTextContent('Standup');
      expect(list).toHaveTextContent('Lunch with Sam');
      expect(
        screen.queryByText('Nothing scheduled today.')
      ).not.toBeInTheDocument();
    });

    it('drops the empty line for a single non-list child', () => {
      render(
        <DashboardSectionCard {...CARD_PROPS}>
          <li>The only entry</li>
        </DashboardSectionCard>
      );

      expect(screen.getByRole('listitem')).toHaveTextContent('The only entry');
      expect(
        screen.queryByText('Nothing scheduled today.')
      ).not.toBeInTheDocument();
    });
  });

  /**
   * The footer is what a section hangs beneath its entries: the agenda's
   * tomorrow disclosure (**W19**) is the first, and it has to sit under the
   * list *and* under the empty line, because "nothing scheduled today" says
   * nothing about tomorrow.
   */
  describe('when given a footer', () => {
    it('renders it beneath the entries', () => {
      render(
        <DashboardSectionCard
          {...CARD_PROPS}
          footer={<button type='button'>Tomorrow</button>}
        >
          <li>The only entry</li>
        </DashboardSectionCard>
      );

      const entry = screen.getByRole('listitem');
      const footer = screen.getByRole('button', { name: 'Tomorrow' });
      expect(footer).toBeInTheDocument();
      expect(
        entry.compareDocumentPosition(footer) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('renders it beneath the empty line when the section holds nothing', () => {
      render(
        <DashboardSectionCard
          {...CARD_PROPS}
          footer={<button type='button'>Tomorrow</button>}
        />
      );

      const emptyLine = screen.getByText('Nothing scheduled today.');
      const footer = screen.getByRole('button', { name: 'Tomorrow' });
      expect(
        emptyLine.compareDocumentPosition(footer) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('renders it alongside a placeholder, leaving the placeholder alone', () => {
      render(
        <DashboardSectionCard
          {...CARD_PROPS}
          placeholder={<p>Loading today&apos;s agenda...</p>}
          footer={<button type='button'>Tomorrow</button>}
        />
      );

      expect(screen.getByText("Loading today's agenda...")).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Tomorrow' })
      ).toBeInTheDocument();
      expect(
        screen.queryByText('Nothing scheduled today.')
      ).not.toBeInTheDocument();
    });

    it('draws nothing extra when a section supplies no footer', () => {
      render(<DashboardSectionCard {...CARD_PROPS} />);

      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
  });

  it('carries its header regardless of whether it holds anything', () => {
    render(<DashboardSectionCard {...CARD_PROPS} />);

    expect(
      screen.getByRole('heading', { level: 3, name: 'Agenda' })
    ).toBeInTheDocument();
    expect(screen.getByText(CARD_PROPS.description)).toBeInTheDocument();
  });
});
