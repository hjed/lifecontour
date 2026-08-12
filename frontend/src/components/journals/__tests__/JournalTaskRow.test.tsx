/**
 * Tests for JournalTaskRow — one task as a journal shows it.
 *
 * The row is read-only in this phase: it displays the task text, its status,
 * its linked contacts and, when the task has lapsed, a marker stating which of
 * the two reasons applies. Actions arrive in ITER18-001 Phase 17, and the
 * "no buttons" test below is what keeps this phase honest about that.
 */

import { render, screen, within } from '@testing-library/react';
import { JournalTaskRow } from '../JournalTaskRow';
import {
  createMockJournalTask,
  createMockTaskJournalRef,
} from '../test-helpers';
import { LapseReason, TaskStatus } from '@/types/tasks';
import type { JournalTaskResource } from '@/types/tasks';

/** Render the row inside the list it always lives in. */
function renderRow(task: JournalTaskResource, journalId = '1') {
  return render(
    <ul>
      <JournalTaskRow task={task} journalId={journalId} />
    </ul>
  );
}

describe('JournalTaskRow', () => {
  it('renders the task text', () => {
    renderRow(createMockJournalTask({ text: 'Return the book to Sarah' }));

    expect(screen.getByText('Return the book to Sarah')).toBeInTheDocument();
  });

  describe('status', () => {
    it.each([
      [TaskStatus.NOT_DONE, 'Not done'],
      [TaskStatus.DONE, 'Done'],
      [TaskStatus.CANCELLED, 'Cancelled'],
    ])('shows %s as "%s"', (status, label) => {
      renderRow(createMockJournalTask({ status }));

      expect(screen.getByText(label)).toBeInTheDocument();
    });

    it.each([[TaskStatus.DONE], [TaskStatus.CANCELLED]])(
      'de-emphasises the text of a %s task without hiding it',
      status => {
        renderRow(createMockJournalTask({ status, text: 'Settled already' }));

        const text = screen.getByText('Settled already');
        expect(text).toBeVisible();
        expect(text).toHaveClass('line-through');
      }
    );

    it('leaves a not-done task undecorated', () => {
      renderRow(createMockJournalTask({ text: 'Still outstanding' }));

      expect(screen.getByText('Still outstanding')).not.toHaveClass(
        'line-through'
      );
    });
  });

  describe('lapsed marker', () => {
    it('states that the date passed', () => {
      renderRow(
        createMockJournalTask({
          lapsed: true,
          lapse_reason: LapseReason.DATE_PASSED,
        })
      );

      const marker = screen.getByTestId('journal-task-lapsed');
      expect(marker).toHaveTextContent(/lapsed/i);
      expect(marker).toHaveTextContent(/date/i);
      expect(marker).not.toHaveTextContent(/cancelled/i);
    });

    it('states that the due journal was cancelled', () => {
      renderRow(
        createMockJournalTask({
          lapsed: true,
          lapse_reason: LapseReason.DUE_JOURNAL_CANCELLED,
        })
      );

      const marker = screen.getByTestId('journal-task-lapsed');
      expect(marker).toHaveTextContent(/lapsed/i);
      expect(marker).toHaveTextContent(/cancelled/i);
    });

    it('words the two reasons differently', () => {
      const { unmount } = renderRow(
        createMockJournalTask({
          lapsed: true,
          lapse_reason: LapseReason.DATE_PASSED,
        })
      );
      const datePassed = screen.getByTestId('journal-task-lapsed').textContent;
      unmount();

      renderRow(
        createMockJournalTask({
          lapsed: true,
          lapse_reason: LapseReason.DUE_JOURNAL_CANCELLED,
        })
      );
      const journalCancelled = screen.getByTestId(
        'journal-task-lapsed'
      ).textContent;

      expect(datePassed).not.toBe(journalCancelled);
    });

    it('carries the fuller explanation as a description', () => {
      renderRow(
        createMockJournalTask({
          lapsed: true,
          lapse_reason: LapseReason.DUE_JOURNAL_CANCELLED,
        })
      );

      expect(screen.getByTestId('journal-task-lapsed')).toHaveAttribute(
        'title',
        expect.stringMatching(/cancelled/i)
      );
    });

    it('falls back to a bare marker when no reason is given', () => {
      renderRow(createMockJournalTask({ lapsed: true, lapse_reason: null }));

      expect(screen.getByTestId('journal-task-lapsed')).toHaveTextContent(
        'Lapsed'
      );
    });

    it('is absent on a task that has not lapsed', () => {
      renderRow(createMockJournalTask({ lapsed: false }));

      expect(
        screen.queryByTestId('journal-task-lapsed')
      ).not.toBeInTheDocument();
    });
  });

  describe('linked contacts', () => {
    it('shows an avatar and the full name of each linked contact', () => {
      renderRow(
        createMockJournalTask({
          contacts: [
            { id: 7, display_name: 'Sarah Chen' },
            { id: 8, display_name: 'Tom Blake', photo_url: null },
          ],
        })
      );

      const contacts = screen.getByTestId('journal-task-contacts');
      expect(within(contacts).getByText('Sarah Chen')).toBeInTheDocument();
      expect(within(contacts).getByText('Tom Blake')).toBeInTheDocument();
      expect(within(contacts).getAllByTestId('avatar-contact')).toHaveLength(2);
    });

    it('renders nothing at all when the task has no contacts', () => {
      renderRow(createMockJournalTask({ contacts: [] }));

      expect(
        screen.queryByTestId('journal-task-contacts')
      ).not.toBeInTheDocument();
    });
  });

  describe('due journal', () => {
    it('names the due journal when it is not the journal being viewed', () => {
      renderRow(
        createMockJournalTask({
          due_journal_id: 42,
          due_journal: createMockTaskJournalRef({
            id: 42,
            title: 'Friday planning',
          }),
        }),
        '1'
      );

      const link = screen.getByRole('link', { name: 'Friday planning' });
      expect(link).toHaveAttribute('href', '/journals/42');
    });

    it('says nothing about the due journal when it is this journal', () => {
      renderRow(
        createMockJournalTask({
          due_journal_id: 1,
          due_journal: createMockTaskJournalRef({ id: 1, title: 'This one' }),
        }),
        '1'
      );

      expect(
        screen.queryByRole('link', { name: 'This one' })
      ).not.toBeInTheDocument();
    });
  });

  it('offers no actions — the row is read-only in this phase', () => {
    renderRow(
      createMockJournalTask({
        lapsed: true,
        lapse_reason: LapseReason.DATE_PASSED,
        contacts: [{ id: 7, display_name: 'Sarah Chen' }],
      })
    );

    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });
});
