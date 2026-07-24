/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { usePathname, useSearchParams } from 'next/navigation';
import { Sidebar } from '../Sidebar';
import { useTags } from '@/lib/api/contacts';
import { useJournalTags } from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';
import { renderWithProviders } from '@/test-utils';

jest.mock('@/lib/api/contacts', () => ({
  useTags: jest.fn(),
  useUpdateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useDeleteTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useCreateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useMergeTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
}));

jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(),
}));

jest.mock('next/navigation', () => ({
  usePathname: jest.fn(() => '/journals'),
  useSearchParams: jest.fn(() => new URLSearchParams()),
}));

const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;
const mockUseJournalTags = useJournalTags as jest.MockedFunction<
  typeof useJournalTags
>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseSearchParams = useSearchParams as jest.MockedFunction<
  typeof useSearchParams
>;

/** Journal tags are UUID-keyed; fixed ids keep assertions readable. */
const PARENT_ID = '11111111-1111-1111-1111-111111111111';
const CHILD_ID = '22222222-2222-2222-2222-222222222222';
const LEAF_ID = '33333333-3333-3333-3333-333333333333';

function journalTag(
  id: string,
  name: string,
  parentId: string | null = null
): JournalTag {
  return { id, name, color: '#3B82F6', parent_id: parentId };
}

/** Point `useJournalTags` at a fixed tag list in a loaded, error-free state. */
function setJournalTags(tags: JournalTag[]): void {
  mockUseJournalTags.mockReturnValue({
    data: { data: tags },
    isLoading: false,
    error: null,
  } as never);
}

/**
 * The Journals section is collapsed by default, so every tag assertion has to
 * open it first.
 */
async function expandJournalsSection(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /journals/i }));
}

describe('Sidebar - Journal Tags', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUsePathname.mockReturnValue('/journals');
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>
    );
    // Contacts have no tags unless a test says otherwise, so journal
    // assertions cannot accidentally match a contact tag.
    mockUseTags.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    } as never);
    setJournalTags([]);
  });

  it('renders a flat journal tag linking to the journals tag filter', async () => {
    setJournalTags([journalTag(LEAF_ID, 'Climbing')]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    const link = screen.getByTestId(`nav-link-journal-tag-${LEAF_ID}`);
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', `/journals?tag=${LEAF_ID}`);
    expect(screen.getByText('Climbing')).toBeInTheDocument();
  });

  it('nests child tags under their parent and hides them until expanded', async () => {
    setJournalTags([
      journalTag(PARENT_ID, 'Outdoors'),
      journalTag(CHILD_ID, 'Climbing', PARENT_ID),
    ]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(screen.getByText('Outdoors')).toBeInTheDocument();

    const toggle = screen.getByTestId(`journal-tag-toggle-${PARENT_ID}`);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    expect(screen.queryByText('Climbing')).not.toBeInTheDocument();
  });

  it('expands and collapses a parent journal tag', async () => {
    setJournalTags([
      journalTag(PARENT_ID, 'Outdoors'),
      journalTag(CHILD_ID, 'Climbing', PARENT_ID),
    ]);

    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);
    await user.click(screen.getByRole('button', { name: /journals/i }));

    const toggle = screen.getByTestId(`journal-tag-toggle-${PARENT_ID}`);

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Climbing')).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Climbing')).not.toBeInTheDocument();
  });

  it('does not render an expand toggle for a leaf journal tag', async () => {
    setJournalTags([journalTag(LEAF_ID, 'Climbing')]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(
      screen.queryByTestId(`journal-tag-toggle-${LEAF_ID}`)
    ).not.toBeInTheDocument();
  });

  it('marks the active journal tag and not All Journals when ?tag= is set', async () => {
    setJournalTags([journalTag(LEAF_ID, 'Climbing')]);
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams(`tag=${LEAF_ID}`) as unknown as ReturnType<
        typeof useSearchParams
      >
    );

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(
      screen.getByTestId(`nav-link-journal-tag-${LEAF_ID}`)
    ).toHaveAttribute('aria-current', 'page');
    expect(
      screen.getByRole('link', { name: 'All Journals' })
    ).not.toHaveAttribute('aria-current');
  });

  it('marks All Journals active when no tag filter is applied', async () => {
    setJournalTags([journalTag(LEAF_ID, 'Climbing')]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(screen.getByRole('link', { name: 'All Journals' })).toHaveAttribute(
      'aria-current',
      'page'
    );
    expect(
      screen.getByTestId(`nav-link-journal-tag-${LEAF_ID}`)
    ).not.toHaveAttribute('aria-current');
  });

  it('does not mark All Journals active on a nested journals route', async () => {
    // `/journals` matches exactly rather than by prefix, so a sub-route such as
    // the outdoor logbook highlights only its own link.
    mockUsePathname.mockReturnValue('/journals/outdoor-logbook');

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(
      screen.getByRole('link', { name: 'Outdoor Logbook' })
    ).toHaveAttribute('aria-current', 'page');
    expect(
      screen.getByRole('link', { name: 'All Journals' })
    ).not.toHaveAttribute('aria-current');
  });

  it('shows a loading placeholder while journal tags load', async () => {
    mockUseJournalTags.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(screen.getByText('Loading tags...')).toBeInTheDocument();
  });

  it('degrades silently when the journal tags request fails', async () => {
    mockUseJournalTags.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load journal tags'),
    } as never);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(
      screen.getByRole('link', { name: 'All Journals' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Outdoor Logbook' })
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Failed to load journal tags')
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('journal-tag-tree-container')
    ).not.toBeInTheDocument();
  });

  it('renders no journal tag tree when there are no journal tags', async () => {
    setJournalTags([]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(
      screen.getByRole('link', { name: 'All Journals' })
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('journal-tag-tree-container')
    ).not.toBeInTheDocument();
  });

  it('keeps the contact and journal tag trees pointed at their own list routes', async () => {
    mockUseTags.mockReturnValue({
      data: {
        data: [
          {
            type: 'tags',
            id: '7',
            attributes: {
              name: 'Work',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
        ],
      },
      isLoading: false,
      error: null,
    } as never);
    setJournalTags([journalTag(LEAF_ID, 'Climbing')]);

    renderWithProviders(<Sidebar />);
    await expandJournalsSection();

    expect(screen.getByTestId('tag-tree-container')).toBeInTheDocument();
    expect(
      screen.getByTestId('journal-tag-tree-container')
    ).toBeInTheDocument();
    expect(screen.getByTestId('nav-link-tag-7')).toHaveAttribute(
      'href',
      '/contacts?tag=7'
    );
    expect(
      screen.getByTestId(`nav-link-journal-tag-${LEAF_ID}`)
    ).toHaveAttribute('href', `/journals?tag=${LEAF_ID}`);
  });
});
