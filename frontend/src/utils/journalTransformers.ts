import {
  JournalResource,
  JournalType,
  JournalTag,
  JournalContactRelationship,
  JournalCalendar,
  EventDateRange,
  ChildJournalSummary,
  JournalTypeData,
} from '@/types/journals';

/**
 * Transformed journal data for display purposes
 */
export interface DisplayJournal {
  id: string;
  title: string;
  content: string;
  event_date_range: EventDateRange;
  types: JournalType[];
  tags: JournalTag[];
  contacts: JournalContactRelationship[];
  calendar?: JournalCalendar | null;
  type_data?: Record<string, JournalTypeData>;
  parent_id?: number | null;
  order?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  // Optional search highlighting fields
  highlighted?: Record<string, string> | null;
  isSearchResult?: boolean;
  highlightedTitle?: string | null;
  highlightedContent?: string | null;
  // Hierarchy metadata
  children?: ChildJournalSummary[];
  children_count?: number | null;
  depth?: number | null;
  // Review indicators
  has_pending_reviews?: boolean;
  // Task indicators
  tasks_due_count?: number | null;
}

/**
 * Transform a JournalResource to DisplayJournal format.
 * This is the single source of truth for journal transformation logic.
 *
 * @param journal - The journal resource to transform
 * @param shouldUseSearch - Whether to extract search highlighting metadata
 * @returns Transformed journal for display
 */
export function transformJournalForDisplay(
  journal: JournalResource,
  shouldUseSearch = false
): DisplayJournal {
  const highlighted = journal.meta?.highlighted as Record<
    string,
    string
  > | null;
  const isSearchResult = shouldUseSearch && !!highlighted;

  // Pre-compute highlighted text for performance
  const highlightedTitle =
    isSearchResult && highlighted?.title ? highlighted.title : null;

  const highlightedContent =
    isSearchResult && highlighted?.content ? highlighted.content : null;

  return {
    id: journal.id,
    title: journal.attributes.title,
    content: journal.attributes.content,
    event_date_range: journal.attributes.event_date_range,
    types: journal.attributes.types,
    tags: journal.attributes.tags,
    contacts: journal.attributes.contacts,
    calendar: journal.attributes.calendar,
    type_data: journal.attributes.type_data,
    parent_id: journal.attributes.parent_id ?? null,
    order: journal.attributes.order ?? null,
    created_at: journal.attributes.created_at,
    updated_at: journal.attributes.updated_at,
    highlighted,
    isSearchResult,
    highlightedTitle,
    highlightedContent,
    children: journal.attributes.children,
    children_count: journal.attributes.children_count ?? null,
    depth: journal.attributes.depth ?? null,
    has_pending_reviews: journal.attributes.has_pending_reviews,
    // Passed through rather than defaulted: null or absent means the endpoint
    // did not compute a count, which the row must not turn into a claim that
    // the journal has nothing due.
    tasks_due_count: journal.attributes.tasks_due_count,
  };
}
