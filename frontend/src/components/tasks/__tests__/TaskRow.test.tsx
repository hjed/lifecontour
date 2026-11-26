/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import {
  createMockTaskJournalRef,
  createTestQueryClient,
} from '@/components/journals/test-helpers';
import { createMockListTaskRead } from '@/test-utils/tasks';
import { TaskStatus, type ListTaskReadResource } from '@/types/tasks';
import { TaskRow } from '../TaskRow';

jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

function renderRow(task: ListTaskReadResource) {
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <ul>
        <TaskRow task={task} />
      </ul>
    </QueryClientProvider>
  );
  return screen.getByTestId(`task-row-${task.id}`);
}

const HOUSE_INSPECTION = createMockTaskJournalRef({
  id: 31,
  title: 'House inspection',
  date: '2026-11-28',
});

describe('TaskRow', () => {
  describe('text and status', () => {
    it('shows the text of an open task, unstruck and unmarked', () => {
      const row = renderRow(createMockListTaskRead({ text: 'Fix the door' }));

      const text = within(row).getByText('Fix the door');
      expect(text).not.toHaveClass('line-through');
      expect(within(row).queryByText('Cancelled')).not.toBeInTheDocument();
    });

    it('strikes through a done task', () => {
      const row = renderRow(
        createMockListTaskRead({
          text: 'Fix the door',
          status: TaskStatus.DONE,
        })
      );

      expect(within(row).getByText('Fix the door')).toHaveClass('line-through');
      expect(within(row).queryByText('Cancelled')).not.toBeInTheDocument();
    });

    it('strikes through a cancelled task and marks it, describing its checkbox', () => {
      const row = renderRow(
        createMockListTaskRead({
          text: 'Fix the door',
          status: TaskStatus.CANCELLED,
        })
      );

      expect(within(row).getByText('Fix the door')).toHaveClass('line-through');
      expect(within(row).getByText('Cancelled')).toBeInTheDocument();
      expect(
        within(row).getByRole('checkbox', { name: 'Done: Fix the door' })
      ).toHaveAccessibleDescription('Cancelled');
    });

    it('offers a checkbox named for the task', () => {
      const row = renderRow(createMockListTaskRead({ text: 'Fix the door' }));

      expect(
        within(row).getByRole('checkbox', { name: 'Done: Fix the door' })
      ).not.toBeChecked();
    });
  });

  describe('icon and flag', () => {
    it('draws the task’s icon glyph as decoration', () => {
      const row = renderRow(createMockListTaskRead({ icon: 'house' }));

      const icon = within(row).getByTestId('task-row-icon');
      expect(icon.querySelector('svg.lucide-house')).toHaveAttribute(
        'aria-hidden',
        'true'
      );
    });

    it('names the task’s icon for assistive technology', () => {
      const row = renderRow(createMockListTaskRead({ icon: 'paw-print' }));

      expect(within(row).getByTestId('task-row-icon')).toHaveTextContent(
        'Paw print icon'
      );
    });

    it('draws no icon when the task has none', () => {
      const row = renderRow(createMockListTaskRead({ icon: null }));

      expect(within(row).queryByTestId('task-row-icon')).toBeNull();
    });

    it('marks a flagged task, straight after its text', () => {
      const row = renderRow(
        createMockListTaskRead({
          flagged: true,
          contacts: [{ id: 5, display_name: 'Dave Nguyen', photo_url: null }],
        })
      );

      const flag = within(row).getByRole('img', { name: 'Flagged' });
      const contacts = within(row).getByRole('list', { name: 'Contacts' });
      expect(
        flag.compareDocumentPosition(contacts) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('does not mark an unflagged task', () => {
      const row = renderRow(createMockListTaskRead({ flagged: false }));

      expect(
        within(row).queryByRole('img', { name: 'Flagged' })
      ).not.toBeInTheDocument();
    });
  });

  describe('dates', () => {
    it('shows a due date as a calendar day', () => {
      const row = renderRow(createMockListTaskRead({ due_date: '2026-11-30' }));

      const chip = within(row).getByTestId('task-row-due-date');
      expect(chip).toHaveTextContent('Mon 30 Nov');
      expect(chip.querySelector('time')).toHaveAttribute(
        'dateTime',
        '2026-11-30'
      );
    });

    it('links the due journal, with its date', () => {
      const row = renderRow(
        createMockListTaskRead({
          due_journal_id: HOUSE_INSPECTION.id,
          due_journal: HOUSE_INSPECTION,
        })
      );

      const link = within(row).getByRole('link', { name: /House inspection/ });
      expect(link).toHaveAttribute('href', '/journals/31');
      expect(link).toHaveTextContent('House inspection · Sat 28 Nov');
      expect(link.querySelector('time')).toHaveAttribute(
        'dateTime',
        '2026-11-28'
      );
    });

    it('says when the due journal is cancelled, and gives no date', () => {
      const cancelled = { ...HOUSE_INSPECTION, cancelled: true };
      const row = renderRow(
        createMockListTaskRead({
          due_journal_id: cancelled.id,
          due_journal: cancelled,
        })
      );

      const link = within(row).getByRole('link', { name: /House inspection/ });
      expect(link).toHaveTextContent('House inspection · journal cancelled');
      expect(link.querySelector('time')).toBeNull();
    });

    it('marks an overdue open task in place of its due date', () => {
      const row = renderRow(
        createMockListTaskRead({ due_date: '2026-11-09', overdue: true })
      );

      const marker = within(row).getByTestId('task-row-overdue');
      expect(marker).toHaveTextContent('Overdue · 9 Nov');
      expect(marker).toHaveAttribute(
        'title',
        'Overdue: its date has passed and it is still not done.'
      );
      expect(within(row).queryByTestId('task-row-due-date')).toBeNull();
    });

    it('keeps the due-journal link beside the overdue marker', () => {
      const row = renderRow(
        createMockListTaskRead({
          due_journal_id: HOUSE_INSPECTION.id,
          due_journal: HOUSE_INSPECTION,
          overdue: true,
        })
      );

      expect(within(row).getByTestId('task-row-overdue')).toHaveTextContent(
        'Overdue · 28 Nov'
      );
      expect(
        within(row).getByRole('link', { name: /House inspection/ })
      ).toBeInTheDocument();
    });

    it.each([TaskStatus.DONE, TaskStatus.CANCELLED])(
      'does not mark a %s task overdue from a payload read before it closed',
      status => {
        const row = renderRow(
          createMockListTaskRead({
            due_date: '2026-11-09',
            overdue: true,
            status,
          })
        );

        expect(within(row).queryByTestId('task-row-overdue')).toBeNull();
      }
    );

    it('shows no date, link or marker on an undated task', () => {
      const row = renderRow(createMockListTaskRead());

      expect(within(row).queryByTestId('task-row-due-date')).toBeNull();
      expect(within(row).queryByRole('link')).toBeNull();
      expect(within(row).queryByTestId('task-row-overdue')).toBeNull();
    });
  });

  describe('contacts', () => {
    it('draws one named avatar per contact', () => {
      const row = renderRow(
        createMockListTaskRead({
          contacts: [
            { id: 5, display_name: 'Dave Nguyen', photo_url: null },
            { id: 6, display_name: 'Sarah Chen', photo_url: null },
          ],
        })
      );

      const contacts = within(row).getByRole('list', { name: 'Contacts' });
      expect(
        within(contacts)
          .getAllByRole('img')
          .map(avatar => avatar.getAttribute('aria-label'))
      ).toEqual(['Dave Nguyen', 'Sarah Chen']);
    });

    it('draws no contacts list when there are none', () => {
      const row = renderRow(createMockListTaskRead({ contacts: [] }));

      expect(
        within(row).queryByRole('list', { name: 'Contacts' })
      ).not.toBeInTheDocument();
    });
  });
});
