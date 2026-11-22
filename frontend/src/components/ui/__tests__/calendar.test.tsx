/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Calendar } from '../calendar';

const MONTH = new Date(2026, 10, 1);

function CalendarHost({
  label,
  onSelect,
}: {
  readonly label: string;
  readonly onSelect: (date: Date | undefined) => void;
}) {
  return (
    <div data-label={label}>
      <Calendar mode='single' defaultMonth={MONTH} onSelect={onSelect} />
    </div>
  );
}

describe('Calendar', () => {
  // A day must be the same DOM node across re-renders of the calendar's
  // parent: a click whose mousedown and mouseup straddle a remount lands on
  // two different nodes, so the browser never fires `click` and the
  // selection is silently lost.
  it('keeps its day buttons mounted when the parent re-renders', () => {
    const onSelect = jest.fn();
    const { rerender } = render(
      <CalendarHost label='before' onSelect={onSelect} />
    );
    const dayBefore = screen.getByRole('button', { name: /November 15th/ });

    rerender(<CalendarHost label='after' onSelect={onSelect} />);

    expect(dayBefore.isConnected).toBe(true);
    expect(screen.getByRole('button', { name: /November 15th/ })).toBe(
      dayBefore
    );
  });

  it('selects a day clicked after the parent re-renders', async () => {
    const user = userEvent.setup();
    const onSelect = jest.fn();
    const { rerender } = render(
      <CalendarHost label='before' onSelect={onSelect} />
    );
    rerender(<CalendarHost label='after' onSelect={onSelect} />);

    await user.click(screen.getByRole('button', { name: /November 15th/ }));

    expect(onSelect).toHaveBeenCalledWith(
      new Date(2026, 10, 15),
      expect.anything(),
      expect.anything(),
      expect.anything()
    );
  });

  // The month/year selects are invisible (`opacity-0`) over their caption,
  // so the wrapper has to show keyboard focus for them.
  it('shows focus on the month and year dropdowns', () => {
    const { container } = render(
      <Calendar
        mode='single'
        captionLayout='dropdown'
        defaultMonth={MONTH}
        startMonth={new Date(2020, 0)}
        endMonth={new Date(2030, 11)}
      />
    );

    const roots = container.querySelectorAll('.rdp-dropdown_root');
    expect(roots.length).toBeGreaterThan(0);
    roots.forEach(root => {
      expect(root).toHaveClass(
        'has-focus:ring-[3px]',
        'has-focus:ring-ring/50'
      );
    });
  });
});
