/**
 * @jest-environment jsdom
 */

/**
 * Tests for JournalTaskRow — one task as a journal shows it.
 *
 * The row displays the task text, its status, its linked contacts and, when
 * the task has lapsed, a marker stating which of the two reasons applies, and
 * it mounts the inline status actions. What those actions *do* is asserted in
 * `JournalTaskActions.test.tsx`; what this file pins is that the row offers
 * them and describes them by the commitment they act on.
 */

import { render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { JournalTaskRow } from '../JournalTaskRow';
import {
  createMockJournalTask,
  createMockTaskJournalRef,
  createTestQueryClient,
} from '../test-helpers';
import { LapseReason, TaskLinkRole, TaskStatus } from '@/types/tasks';
import type { JournalTaskResource } from '@/types/tasks';

// `jest.setup.ts` narrows `@/lib/constants` to the auth endpoints, which would
// leave the actions' mutation hooks without `API_ENDPOINTS.TASKS`.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

/** Render the row inside the list — and the provider — it always lives in. */
function renderRow(
  task: JournalTaskResource,
  journalId = '1',
  role: TaskLinkRole = TaskLinkRole.DUE
) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <ul>
        <JournalTaskRow task={task} journalId={journalId} role={role} />
      </ul>
    </QueryClientProvider>
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

  /**
   * The inverse of the assertion this file carried through Phase 16, which
   * required the busiest row to render zero buttons. It was written so that
   * adding the actions would have to come back and change it, rather than
   * leaving a passing test that quietly meant nothing.
   */
  it('offers its actions inline, described by the task they act on', () => {
    renderRow(
      createMockJournalTask({
        lapsed: true,
        lapse_reason: LapseReason.DATE_PASSED,
        contacts: [{ id: 7, display_name: 'Sarah Chen' }],
      })
    );

    const group = screen.getByRole('group', { name: 'Task actions' });
    expect(
      within(group).getByRole('button', { name: 'Mark done' })
    ).toBeVisible();
    expect(
      within(group).getByRole('button', { name: 'Cancel task' })
    ).toBeVisible();
    expect(group.getAttribute('aria-describedby')).toBe(
      screen.getByTestId('journal-task-text').id
    );
  });

  it('keeps a lapsed row actionable rather than presenting it as settled', () => {
    renderRow(
      createMockJournalTask({
        lapsed: true,
        lapse_reason: LapseReason.DUE_JOURNAL_CANCELLED,
      })
    );

    expect(screen.getByRole('button', { name: 'Mark done' })).toBeEnabled();
  });

  /**
   * The row does not decide the rule — `linkRemovable` does, and it is tested
   * exhaustively over the enum there. What the row owes is the wiring: the
   * role it was rendered with reaches the actions group, so the same task in
   * two groups gets two different offers.
   */
  describe('the role it was rendered in', () => {
    const REMOVE = 'Remove mention from this journal';

    it('offers a remove on a mentioned row', () => {
      renderRow(createMockJournalTask(), '1', TaskLinkRole.MENTIONED);

      expect(screen.getByRole('button', { name: REMOVE })).toBeInTheDocument();
    });

    it.each([TaskLinkRole.DUE, TaskLinkRole.CREATED])(
      'offers none on a %s row',
      role => {
        renderRow(createMockJournalTask(), '1', role);

        expect(
          screen.queryByRole('button', { name: REMOVE })
        ).not.toBeInTheDocument();
      }
    );
  });
});
