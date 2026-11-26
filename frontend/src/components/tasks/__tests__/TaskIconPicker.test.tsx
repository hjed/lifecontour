/**
 * The icon picker: the fixed set as a radio group, searchable by name, with
 * "No icon" first and always on offer.
 *
 * Rendered inside a small harness that holds the value, so a choice moves the
 * checked tile the way it will in a form, while the spy records exactly what
 * the picker handed its caller.
 */

import { useState } from 'react';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { TaskIconPicker } from '@/components/tasks/TaskIconPicker';
import { TASK_ICON_DISPLAY } from '@/lib/task-icon-display';
import { TASK_ICONS, type TaskIcon } from '@/types/task-icons';

function Harness({
  initial,
  onChange,
  disabled,
}: {
  readonly initial: TaskIcon | null;
  readonly onChange: (icon: TaskIcon | null) => void;
  readonly disabled?: boolean;
}) {
  const [value, setValue] = useState<TaskIcon | null>(initial);
  return (
    <TaskIconPicker
      value={value}
      disabled={disabled}
      onChange={icon => {
        setValue(icon);
        onChange(icon);
      }}
    />
  );
}

function renderPicker(
  initial: TaskIcon | null,
  options: { disabled?: boolean } = {}
) {
  const onChange = jest.fn<void, [TaskIcon | null]>();
  const user = userEvent.setup();
  render(
    <Harness
      initial={initial}
      onChange={onChange}
      disabled={options.disabled}
    />
  );
  return { onChange, user };
}

const group = () => screen.getByRole('radiogroup', { name: 'Icon' });
const radioNames = () =>
  within(group())
    .getAllByRole('radio')
    .map(radio => radio.getAttribute('aria-label'));
const searchField = () =>
  screen.getByRole('searchbox', { name: 'Search icons' });

/**
 * Presses an arrow key and holds it until Radix has moved focus.
 *
 * Radix moves focus on a timeout after the keydown, and a radio is checked by
 * that focus only while the arrow key is still down — as it is in a browser,
 * where the key is released long after the timeout runs.
 */
async function pressArrow(
  user: ReturnType<typeof userEvent.setup>,
  key: 'ArrowRight' | 'ArrowDown' | 'ArrowLeft'
) {
  await user.keyboard(`{${key}>}`);
  await act(() => new Promise(resolve => setTimeout(resolve, 0)));
  await user.keyboard(`{/${key}}`);
}

describe('TaskIconPicker', () => {
  describe('the set on offer', () => {
    it('offers "No icon" first, then every icon in published order', () => {
      renderPicker(null);

      expect(radioNames()).toEqual([
        'No icon',
        ...TASK_ICONS.map(key => TASK_ICON_DISPLAY[key].label),
      ]);
    });

    it('checks "No icon" when the task has none', () => {
      renderPicker(null);

      expect(screen.getByRole('radio', { name: 'No icon' })).toBeChecked();
      expect(screen.getByText('No icon chosen')).toBeInTheDocument();
    });

    it('checks only the chosen icon, and names it', () => {
      renderPicker('tent');

      const checked = within(group())
        .getAllByRole('radio')
        .filter(radio => radio.getAttribute('aria-checked') === 'true');
      expect(checked).toEqual([screen.getByRole('radio', { name: 'Tent' })]);
      expect(screen.getByText('Chosen: Tent')).toBeInTheDocument();
    });
  });

  describe('choosing', () => {
    it('hands the caller the key of the icon clicked', async () => {
      const { onChange, user } = renderPicker(null);

      await user.click(screen.getByRole('radio', { name: 'Tent' }));

      expect(onChange).toHaveBeenLastCalledWith('tent');
      expect(screen.getByRole('radio', { name: 'Tent' })).toBeChecked();
    });

    it('hands the caller null for "No icon"', async () => {
      const { onChange, user } = renderPicker('tent');

      await user.click(screen.getByRole('radio', { name: 'No icon' }));

      expect(onChange).toHaveBeenLastCalledWith(null);
      expect(screen.getByText('No icon chosen')).toBeInTheDocument();
    });
  });

  describe('search', () => {
    it('says how many icons it offers before anything is typed', () => {
      renderPicker(null);

      expect(screen.getByRole('status')).toHaveTextContent('40 icons');
    });

    it('narrows the grid to icons whose name matches, keeping "No icon"', async () => {
      const { user } = renderPicker(null);

      await user.type(searchField(), 'shop');

      expect(radioNames()).toEqual(['No icon', 'Shopping cart']);
      expect(screen.getByRole('status')).toHaveTextContent('1 icon');
    });

    it('says when nothing matches, and still offers "No icon"', async () => {
      const { user } = renderPicker(null);

      await user.type(searchField(), 'zzz');

      expect(radioNames()).toEqual(['No icon']);
      expect(screen.getByRole('status')).toHaveTextContent(
        'No icons match "zzz"'
      );
    });

    it('points the search field at the grid it filters', () => {
      renderPicker(null);

      expect(searchField()).toHaveAttribute('aria-controls', group().id);
    });
  });

  describe('keyboard', () => {
    it('tabs from the search field to the chosen icon', async () => {
      const { user } = renderPicker('list');

      await user.click(searchField());
      await user.tab();

      expect(screen.getByRole('radio', { name: 'List' })).toHaveFocus();
    });

    it('moves the choice with the arrow keys', async () => {
      const { onChange, user } = renderPicker('list');

      await user.click(searchField());
      await user.tab();
      await pressArrow(user, 'ArrowRight');
      expect(onChange).toHaveBeenLastCalledWith('clipboard-list');

      await pressArrow(user, 'ArrowDown');
      expect(onChange).toHaveBeenLastCalledWith('bookmark');
      expect(screen.getByRole('radio', { name: 'Bookmark' })).toHaveFocus();
      expect(screen.getByRole('radio', { name: 'Bookmark' })).toBeChecked();
    });

    it('wraps from the first tile to the last', async () => {
      const { onChange, user } = renderPicker(null);

      await user.click(searchField());
      await user.tab();
      await pressArrow(user, 'ArrowLeft');

      expect(onChange).toHaveBeenLastCalledWith('camera');
    });

    it('still reaches the grid when the search hides the chosen icon, and chooses with Space', async () => {
      const { onChange, user } = renderPicker('tent');

      await user.type(searchField(), 'shop');
      await user.tab();

      const noIcon = screen.getByRole('radio', { name: 'No icon' });
      expect(noIcon).toHaveFocus();
      expect(onChange).not.toHaveBeenCalled();

      await user.keyboard(' ');

      expect(onChange).toHaveBeenLastCalledWith(null);
      expect(noIcon).toBeChecked();
    });
  });

  it('can be disabled as a whole', () => {
    renderPicker('tent', { disabled: true });

    expect(searchField()).toBeDisabled();
    within(group())
      .getAllByRole('radio')
      .forEach(radio => expect(radio).toBeDisabled());
  });
});
