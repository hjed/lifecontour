/**
 * Tests for JournalTasksSection — a journal's tasks, grouped by link role.
 *
 * The listing returns each task **once** in `data` however many roles it holds
 * in the journal, with the grouping stated separately in `meta.groups` as
 * ordered id lists. The section's job is to honour that contract: walk the id
 * lists, not `data`; render a task under each group it belongs to; and show
 * nothing at all rather than an empty container when there is nothing to show.
 */

import { render, screen, within } from '@testing-library/react';
import { JournalTasksSection } from '../JournalTasksSection';
import { createMockJournalTask } from '../test-helpers';
import { TaskLinkRole } from '@/types/tasks';
import type { JournalTaskResource, JournalTasksResponse } from '@/types/tasks';
import { useJournalTasks } from '@/lib/api/tasks';

// The rows mount inline status actions, whose mutation hooks would otherwise
// want a `QueryClientProvider` this suite has no use for: what it asserts is
// the grouping contract, and the actions carry their own tests.
jest.mock('@/lib/api/tasks', () => ({
  useJournalTasks: jest.fn(),
  useUpdateTask: () => ({ mutate: jest.fn(), isPending: false }),
  useDeleteTask: () => ({ mutate: jest.fn(), isPending: false }),
  useRetargetTask: () => ({ mutate: jest.fn(), isPending: false }),
  useTaskWriteInFlight: () => false,
  useDetachTaskIntermediateJournal: () => ({
    mutate: jest.fn(),
    isPending: false,
  }),
  useAttachTaskIntermediateJournal: () => ({
    mutate: jest.fn(),
    isPending: false,
  }),
  useCreateTask: () => ({ mutate: jest.fn(), isPending: false }),
  TASK_JOURNAL_IS_ANCHOR: 'TASK_JOURNAL_IS_ANCHOR',
  TaskApiError: class TaskApiError extends Error {},
  TASK_REOPEN_NOT_ACKNOWLEDGED: 'TASK_REOPEN_NOT_ACKNOWLEDGED',
  TASK_DUE_JOURNAL_NOT_FUTURE: 'TASK_DUE_JOURNAL_NOT_FUTURE',
  TASK_VALIDATION_ERROR: 'TASK_VALIDATION_ERROR',
  CONTACT_NOT_FOUND: 'CONTACT_NOT_FOUND',
  taskValidationField: () => null,
}));

const mockUseJournalTasks = useJournalTasks as jest.MockedFunction<
  typeof useJournalTasks
>;

type Groups = Partial<JournalTasksResponse['meta']['groups']>;

/** Point the mocked hook at a settled listing. */
function mockListing(data: JournalTaskResource[], groups: Groups) {
  mockUseJournalTasks.mockReturnValue({
    data: {
      data,
      meta: { groups: { due: [], created: [], mentioned: [], ...groups } },
    },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useJournalTasks>);
}

function mockState(state: { isLoading?: boolean; isError?: boolean }) {
  mockUseJournalTasks.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    ...state,
  } as unknown as ReturnType<typeof useJournalTasks>);
}

const DUE_HEADING = 'Due in this journal';
const CREATED_HEADING = 'Created in this journal';
const MENTIONED_HEADING = 'Mentioned in this journal';

beforeEach(() => {
  jest.clearAllMocks();
});

describe('JournalTasksSection', () => {
  /**
   * The grouping is read from `meta.groups` on one unfiltered listing, never
   * from three role-filtered ones. Asserted over every call rather than by
   * counting them: the card also mounts the attach dialog, which reads the
   * same hook for whichever journal the user names in it, so a count would be
   * measuring how many components are on screen rather than what they ask for.
   */
  it('asks for every role in one request rather than filtering', () => {
    mockListing([], {});

    render(<JournalTasksSection journalId='7' />);

    const calls = mockUseJournalTasks.mock.calls;
    // Exactly one journal is ever asked about — the one being viewed. The
    // dialog reads the same hook, but with `''` until a journal is named in
    // it, which the hook disables; anything else here would be a second
    // listing this surface does not need.
    expect(new Set(calls.map(([journalId]) => journalId))).toEqual(
      new Set(['7', ''])
    );
    calls.forEach(([, options]) => {
      expect(options?.role).toBeUndefined();
    });
  });

  describe('the three groups', () => {
    it('renders due, created and mentioned in that order', () => {
      mockListing(
        [
          createMockJournalTask({ id: '1', text: 'Due task' }),
          createMockJournalTask({ id: '2', text: 'Created task' }),
          createMockJournalTask({ id: '3', text: 'Mentioned task' }),
        ],
        { due: [1], created: [2], mentioned: [3] }
      );

      render(<JournalTasksSection journalId='1' />);

      expect(screen.getByText('Due task')).toBeInTheDocument();
      expect(screen.getByText('Created task')).toBeInTheDocument();
      expect(screen.getByText('Mentioned task')).toBeInTheDocument();
      expect(
        screen
          .getAllByRole('heading', { level: 4 })
          .map(heading => heading.textContent)
      ).toEqual([DUE_HEADING, CREATED_HEADING, MENTIONED_HEADING]);
    });

    it('omits a group with no tasks entirely', () => {
      mockListing([createMockJournalTask({ id: '1', text: 'Due task' })], {
        due: [1],
      });

      render(<JournalTasksSection journalId='1' />);

      expect(screen.getByText(DUE_HEADING)).toBeInTheDocument();
      expect(screen.queryByText(CREATED_HEADING)).not.toBeInTheDocument();
      expect(screen.queryByText(MENTIONED_HEADING)).not.toBeInTheDocument();
    });

    it('renders a task holding two roles under both of its groups', () => {
      mockListing(
        [
          createMockJournalTask({
            id: '1',
            text: 'Anchored twice',
            link_roles: [TaskLinkRole.DUE, TaskLinkRole.CREATED],
          }),
        ],
        { due: [1], created: [1] }
      );

      render(<JournalTasksSection journalId='1' />);

      const due = screen.getByRole('region', { name: DUE_HEADING });
      const created = screen.getByRole('region', { name: CREATED_HEADING });
      expect(within(due).getByText('Anchored twice')).toBeInTheDocument();
      expect(within(created).getByText('Anchored twice')).toBeInTheDocument();
    });

    it('follows the order meta.groups gives, not the order of data', () => {
      mockListing(
        [
          createMockJournalTask({ id: '3', text: 'Third' }),
          createMockJournalTask({ id: '1', text: 'First' }),
          createMockJournalTask({ id: '2', text: 'Second' }),
        ],
        { due: [1, 2, 3] }
      );

      render(<JournalTasksSection journalId='1' />);

      const rows = within(
        screen.getByRole('region', { name: DUE_HEADING })
      ).getAllByRole('listitem');
      expect(rows.map(row => row.textContent)).toEqual([
        expect.stringContaining('First'),
        expect.stringContaining('Second'),
        expect.stringContaining('Third'),
      ]);
    });

    it('skips an id the listing did not resolve to a task', () => {
      mockListing([createMockJournalTask({ id: '1', text: 'The real one' })], {
        due: [1, 99],
      });

      render(<JournalTasksSection journalId='1' />);

      const rows = within(
        screen.getByRole('region', { name: DUE_HEADING })
      ).getAllByRole('listitem');
      expect(rows).toHaveLength(1);
      expect(screen.getByText('The real one')).toBeInTheDocument();
    });
  });

  describe('accessible grouping', () => {
    it('labels each group as a region wrapping its own list', () => {
      mockListing(
        [
          createMockJournalTask({ id: '1', text: 'Due task' }),
          createMockJournalTask({ id: '2', text: 'Mentioned task' }),
        ],
        { due: [1], mentioned: [2] }
      );

      render(<JournalTasksSection journalId='1' />);

      const due = screen.getByRole('region', { name: DUE_HEADING });
      const mentioned = screen.getByRole('region', { name: MENTIONED_HEADING });
      expect(within(due).getByRole('list')).toBeInTheDocument();
      expect(within(mentioned).getByRole('list')).toBeInTheDocument();
      expect(within(due).getAllByRole('listitem')).toHaveLength(1);
    });

    it('gives the section itself a heading above the group headings', () => {
      mockListing([createMockJournalTask({ id: '1' })], { due: [1] });

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.getByRole('heading', { level: 3, name: 'Tasks' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('heading', { level: 4, name: DUE_HEADING })
      ).toBeInTheDocument();
    });
  });

  /**
   * Criterion 2, asserted where the two halves of it meet: the remove
   * affordance follows the **group**, not the task. A retarget onto a journal
   * the task already mentioned leaves it due *and* mentioned here, the listing
   * names it in both groups, and only the mention is removable — the anchors
   * are reachable only through `create_task` and `retarget_due_journal`.
   */
  describe('where the remove affordance is offered', () => {
    const REMOVE = 'Remove mention from this journal';

    it('offers it under Mentioned and not under Due for one task in both', () => {
      mockListing(
        [
          createMockJournalTask({
            id: '1',
            text: 'Due here and mentioned here',
            link_roles: [TaskLinkRole.DUE, TaskLinkRole.MENTIONED],
          }),
        ],
        { due: [1], mentioned: [1] }
      );

      render(<JournalTasksSection journalId='1' />);

      const due = screen.getByRole('region', { name: DUE_HEADING });
      const mentioned = screen.getByRole('region', {
        name: MENTIONED_HEADING,
      });
      expect(
        within(due).queryByRole('button', { name: REMOVE })
      ).not.toBeInTheDocument();
      expect(
        within(mentioned).getByRole('button', { name: REMOVE })
      ).toBeInTheDocument();
    });

    it('offers it on no row of a journal that only anchors its tasks', () => {
      mockListing(
        [
          createMockJournalTask({ id: '1', text: 'Due task' }),
          createMockJournalTask({ id: '2', text: 'Created task' }),
        ],
        { due: [1], created: [2] }
      );

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.queryByRole('button', { name: REMOVE })
      ).not.toBeInTheDocument();
    });
  });

  /**
   * Phase 16 rendered nothing at all when a journal held no tasks. Criterion 1
   * of Phase 19 needs somewhere to attach *from*, and the journal most likely
   * to want it is exactly the one with no tasks yet — so a listing that has
   * *loaded* now renders the card, while the **loading pass still renders
   * nothing**, which is what Phase 16's reason was actually about: no skeleton
   * flashing on nearly every journal detail view.
   */
  describe('when the journal has no tasks', () => {
    it('renders the card so a task can still be attached to it', () => {
      mockListing([], { due: [], created: [], mentioned: [] });

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.getByRole('button', { name: 'Attach task' })
      ).toBeInTheDocument();
      expect(screen.getByText(/no tasks are linked/i)).toBeInTheDocument();
    });

    it('shows no group headings for groups that do not exist', () => {
      mockListing([], { due: [], created: [], mentioned: [] });

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.queryByRole('heading', { level: 4 })
      ).not.toBeInTheDocument();
    });

    it('renders nothing at all while the listing is loading', () => {
      mockState({ isLoading: true });

      const { container } = render(<JournalTasksSection journalId='1' />);

      expect(container).toBeEmptyDOMElement();
    });
  });

  describe('the attach affordance', () => {
    it('sits in the card header on a journal that does have tasks', () => {
      mockListing([createMockJournalTask({ id: '1', text: 'Due task' })], {
        due: [1],
      });

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.getByRole('button', { name: 'Attach task' })
      ).toBeInTheDocument();
    });

    /**
     * The dialog excludes tasks already linked here, and it reads that set from
     * the listing this section has in hand. A failed listing does not have it,
     * so offering the affordance would mean offering a picker that could not
     * keep the two refusals off the screen.
     */
    it('is not offered when the listing failed', () => {
      mockState({ isError: true });

      render(<JournalTasksSection journalId='1' />);

      expect(
        screen.queryByRole('button', { name: 'Attach task' })
      ).not.toBeInTheDocument();
    });

    /**
     * A *refresh* that fails is not a listing that failed. React Query keeps
     * the previous `data` and only sets the status, so a refetch error — a
     * window refocus while the network is down — must not replace a card that
     * has perfectly good tasks to show. It would take any open attach dialog
     * with it, closing over a request that may already have left, which is the
     * one outcome that dialog's close guard exists to prevent.
     */
    it('survives a failed refresh that still has tasks to show', () => {
      mockUseJournalTasks.mockReturnValue({
        data: {
          data: [createMockJournalTask({ id: '1', text: 'Due task' })],
          meta: { groups: { due: [1], created: [], mentioned: [] } },
        },
        isLoading: false,
        isError: true,
      } as unknown as ReturnType<typeof useJournalTasks>);

      render(<JournalTasksSection journalId='1' />);

      expect(screen.getByText('Due task')).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Attach task' })
      ).toBeInTheDocument();
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
  });

  /**
   * The create affordance answers to a different rule from the attach one.
   * Attaching needs the set of tasks already linked here — which it reads from
   * this listing — so it is withheld when the listing failed. Creating depends
   * on nothing from the listing at all: the journal being viewed is the
   * creating journal, and the due journal comes from the picker's own read. So
   * withholding it there would be a restriction with no reason behind it, and
   * a journal whose tasks could not be loaded is not a journal a user should
   * be unable to write a commitment down in.
   */
  describe('the create affordance', () => {
    const createButton = () =>
      screen.queryByRole('button', { name: /new task/i });

    it('sits in the card header on a journal that has tasks', () => {
      mockListing([createMockJournalTask({ id: '1', text: 'Due task' })], {
        due: [1],
      });

      render(<JournalTasksSection journalId='1' />);

      expect(createButton()).toBeInTheDocument();
    });

    it('is offered on a journal with no tasks yet', () => {
      mockListing([], {});

      render(<JournalTasksSection journalId='1' />);

      expect(createButton()).toBeInTheDocument();
    });

    it('is offered even when the listing failed', () => {
      mockState({ isError: true });

      render(<JournalTasksSection journalId='1' />);

      expect(createButton()).toBeInTheDocument();
      // The attach affordance still is not, and the difference is the point.
      expect(
        screen.queryByRole('button', { name: 'Attach task' })
      ).not.toBeInTheDocument();
    });

    /**
     * The loading pass renders nothing at all — most journals hold no tasks,
     * so a card that appeared and then rearranged itself would flicker on
     * nearly every journal detail view.
     */
    it('is not offered while the listing loads', () => {
      mockState({ isLoading: true });

      render(<JournalTasksSection journalId='1' />);

      expect(createButton()).not.toBeInTheDocument();
    });

    it('opens nothing until it is asked to', () => {
      mockListing([], {});

      render(<JournalTasksSection journalId='1' />);

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  describe('when the listing fails', () => {
    it('says so rather than looking like a journal with no tasks', () => {
      mockState({ isError: true });

      const { container } = render(<JournalTasksSection journalId='1' />);

      expect(container).not.toBeEmptyDOMElement();
      expect(screen.getByRole('status')).toHaveTextContent(/tasks/i);
    });
  });
});
