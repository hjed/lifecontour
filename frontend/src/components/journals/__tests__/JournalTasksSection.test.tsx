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

jest.mock('@/lib/api/tasks', () => ({
  useJournalTasks: jest.fn(),
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
  it('asks for every role in one request rather than filtering', () => {
    mockListing([], {});

    render(<JournalTasksSection journalId='7' />);

    expect(mockUseJournalTasks).toHaveBeenCalledTimes(1);
    const [journalId, options] = mockUseJournalTasks.mock.calls[0];
    expect(journalId).toBe('7');
    expect(options?.role).toBeUndefined();
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

  describe('when there is nothing to show', () => {
    it('renders nothing rather than an empty container', () => {
      mockListing([], { due: [], created: [], mentioned: [] });

      const { container } = render(<JournalTasksSection journalId='1' />);

      expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing while the listing is loading', () => {
      mockState({ isLoading: true });

      const { container } = render(<JournalTasksSection journalId='1' />);

      expect(container).toBeEmptyDOMElement();
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
