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
import userEvent from '@testing-library/user-event';
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

// The history disclosure mounts the shared feed, which reaches the network
// through `useTaskHistory`. Only that export is replaced; the row's action
// mutations still use the real client.
const mockUseTaskHistory = jest.fn();
jest.mock('@/lib/api/tasks', () => ({
  ...jest.requireActual('@/lib/api/tasks'),
  useTaskHistory: (...args: unknown[]) => mockUseTaskHistory(...args),
}));

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

/**
 * The task's own change history, on the journal that owns it.
 *
 * Tasks have no route, so ITER18-003 Phase 8 chose a task-scoped read and this
 * is where it is rendered: an expandable row on the journal, using the same
 * activity feed the contact and journal pages use rather than a bespoke list.
 */
describe('the history disclosure', () => {
  const SHOW = 'Show history for “Print the permit”';
  const HIDE = 'Hide history for “Print the permit”';

  beforeEach(() => {
    mockUseTaskHistory.mockClear();
    mockUseTaskHistory.mockReturnValue({
      data: {
        data: [
          {
            type: 'task_history',
            id: 'h1',
            attributes: {
              entity_type: 'task',
              entity_id: 1,
              field_name: 'status',
              old_value: 'not_done',
              new_value: 'done',
              changed_by: 'ui',
              source: 'ui',
              created_at: '2024-01-15T10:30:00Z',
            },
          },
        ],
        meta: { total_count: 1, page_count: 1, current_page: 1, per_page: 10 },
      },
      isLoading: false,
      error: null,
      isFetching: false,
    });
  });

  it('is collapsed to begin with', () => {
    renderRow(createMockJournalTask());

    const trigger = screen.getByRole('button', { name: SHOW });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('activity-feed')).not.toBeInTheDocument();
  });

  it('does not fetch a history nobody has asked for', () => {
    // A journal can hold many tasks. Rendering the section must not cost one
    // history request per row, so the feed is not mounted while the row is
    // collapsed — the hook is never called at all.
    renderRow(createMockJournalTask());

    expect(mockUseTaskHistory).not.toHaveBeenCalled();
  });

  it('names the commitment it belongs to, not just "history"', () => {
    // Every row's trigger would otherwise be called the same thing, which is
    // what a screen-reader user hears when they tab through ten of them.
    renderRow(createMockJournalTask({ text: 'Return the book to Sarah' }));

    expect(
      screen.getByRole('button', {
        name: 'Show history for “Return the book to Sarah”',
      })
    ).toBeInTheDocument();
  });

  it('opens on click and renders the shared feed', async () => {
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    const trigger = screen.getByRole('button', { name: HIDE });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(await screen.findByTestId('activity-feed')).toBeInTheDocument();
    expect(
      screen.getByText('Status changed from Not done to Done')
    ).toBeInTheDocument();
  });

  it('points aria-controls at the panel it opens', async () => {
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    const trigger = screen.getByRole('button', { name: HIDE });
    const panelId = trigger.getAttribute('aria-controls');
    expect(panelId).toBeTruthy();
    expect(document.getElementById(panelId as string)).toContainElement(
      screen.getByTestId('activity-feed')
    );
  });

  it('fetches only once it is open', async () => {
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    expect(mockUseTaskHistory).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ page: 1 })
    );
  });

  it('opens from the keyboard', async () => {
    renderRow(createMockJournalTask());

    const trigger = screen.getByRole('button', { name: SHOW });
    trigger.focus();
    await userEvent.keyboard('{Enter}');

    expect(screen.getByRole('button', { name: HIDE })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
  });

  it('closes again', async () => {
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));
    await userEvent.click(screen.getByRole('button', { name: HIDE }));

    expect(screen.queryByTestId('activity-feed')).not.toBeInTheDocument();
  });

  it('offers no action inside the history it renders', async () => {
    // The record is not a third working surface: an entry cannot be actioned
    // from here any more than it can from the contact page. The row's own
    // status actions live outside the panel and are unaffected.
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    const panel = screen.getByTestId('activity-feed');
    const actionable = within(panel)
      .queryAllByRole('button')
      .filter(
        button =>
          !(button.getAttribute('data-testid') ?? '').startsWith(
            'provenance-trigger-'
          )
      );
    expect(actionable).toHaveLength(0);
    expect(within(panel).queryAllByRole('checkbox')).toHaveLength(0);
  });
});

/**
 * How the disclosure's panel is named and where it sits.
 *
 * Both are consequences of the row living inside a list on a page that already
 * has an "Activity" feed of its own.
 */
describe('the history panel', () => {
  const SHOW = 'Show history for “Print the permit”';

  beforeEach(() => {
    mockUseTaskHistory.mockClear();
    mockUseTaskHistory.mockReturnValue({
      data: { data: [], meta: { total_count: 0 } },
      isLoading: false,
      error: null,
      isFetching: false,
    });
  });

  it('adds no heading of its own', async () => {
    // The journal page's own "Activity" heading is already an h3; one per open
    // task row would be a run of identically-named headings inside a list.
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
  });

  it('takes its name from the trigger that opened it', async () => {
    renderRow(createMockJournalTask());

    await userEvent.click(screen.getByRole('button', { name: SHOW }));

    const panel = screen.getByRole('region', {
      name: 'Hide history for “Print the permit”',
    });
    expect(panel).toContainElement(screen.getByTestId('activity-feed'));
  });

  it('sits after the task’s contacts, not between them and the task', async () => {
    // Expanding a history must not push the people a commitment involves away
    // from the commitment: the specification asks for the contact to be shown
    // on the task wherever the task is displayed.
    renderRow(
      createMockJournalTask({
        contacts: [{ id: 5, display_name: 'Sarah Chen', photo_url: null }],
      })
    );

    const contacts = screen.getByTestId('journal-task-contacts');
    const trigger = screen.getByRole('button', { name: SHOW });

    expect(
      contacts.compareDocumentPosition(trigger) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });
});
