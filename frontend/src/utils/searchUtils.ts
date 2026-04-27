import { ContactResource } from '@/types/contacts';
import { SearchResultResource } from '@/types/search';
import { DisplayJournal } from './journalTransformers';
import {
  JournalType,
  JournalContactRelationshipType,
  JournalTag,
  JournalContactRelationship,
} from '@/types/journals';

export interface GroupedSearchResults {
  contacts: ContactResource[];
  journals: SearchResultResource[];
}

/**
 * Ranking signals extracted from a contact's search metadata.
 * These signals are populated by the backend from MeiliSearch index data.
 */
export interface ContactRankingSignals {
  isFavourite: boolean;
  hasSummary: boolean;
  journalCount30d: number;
  activityCount30d: number;
  lastActivityDate: string | null;
  relationships: string[];
}

/**
 * Extracts ranking signals from a ContactResource's meta.search_metadata.
 * Returns sensible defaults when metadata is absent or incomplete.
 * @param contact ContactResource with optional meta.search_metadata
 * @returns Extracted ranking signals
 */
export function extractContactRankingSignals(
  contact: ContactResource
): ContactRankingSignals {
  const meta = (contact.meta?.search_metadata ?? {}) as Record<string, unknown>;

  return {
    isFavourite: (meta.is_favourite as boolean) ?? false,
    hasSummary: (meta.has_summary as boolean) ?? false,
    journalCount30d: (meta.journal_count_30d as number) ?? 0,
    activityCount30d: (meta.activity_count_30d as number) ?? 0,
    lastActivityDate: (meta.last_activity_date as string) ?? null,
    relationships: (meta.relationships as string[]) ?? [],
  };
}

/**
 * Groups a mixed array of search results into categories based on their type and entity_type.
 * @param results Mixed search results array
 * @returns Grouped results with contacts and journals arrays
 */
export function groupSearchResults(
  results: (ContactResource | SearchResultResource)[]
): GroupedSearchResults {
  const grouped: GroupedSearchResults = {
    contacts: [],
    journals: [],
  };

  if (!results) return grouped;

  for (const item of results) {
    if (item.type === 'contacts') {
      grouped.contacts.push(item as ContactResource);
    } else if (item.type === 'search-results') {
      const searchResult = item as SearchResultResource;
      if (
        searchResult.attributes.entity_type === 'journal' ||
        searchResult.attributes.entity_type === 'journal_entries'
      ) {
        grouped.journals.push(searchResult);
      }
    }
  }

  return grouped;
}

/**
 * Transforms a SearchResultResource (representing a journal) into a DisplayJournal object.
 * Extracts data from the search_metadata payload if available, or falls back to basic attributes.
 * @param result SearchResultResource representing a journal
 * @returns DisplayJournal object suitable for rendering
 */
export function transformSearchResultToDisplayJournal(
  result: SearchResultResource
): DisplayJournal {
  const meta = (result.meta?.search_metadata as Record<string, unknown>) || {};

  // Extract highlighting
  const highlighted = (meta._formatted as Record<string, string>) || {};
  const isSearchResult = true;

  const highlightedTitle = highlighted.title || null;
  const highlightedContent = highlighted.content || null;

  // Fallback dates
  const fallbackDate = result.attributes.created_at || new Date().toISOString();

  // Create tags
  const tagIds: string[] = (meta.tag_ids as string[]) || [];
  const tags: JournalTag[] = tagIds.map(id => ({
    id,
    name: `Tag ${id}`, // We don't have the tag name, but it's not strictly required by UI
  }));

  // Create contacts
  const contactIds: string[] = (meta.contact_ids as string[]) || [];
  const contacts: JournalContactRelationship[] = contactIds.map(id => ({
    id, // JournalContactRelationship.id is the contact ID
    name: `Contact ${id}`,
    relationship_type: JournalContactRelationshipType.MENTION,
  }));

  return {
    id:
      result.meta?.original_id?.toString() || result.id.replace('journal-', ''),
    title: result.attributes.title || (meta.title as string) || 'Untitled',
    content: result.attributes.content || (meta.content as string) || '',
    event_date_range: {
      start: (meta.event_date_range_start as string) || fallbackDate,
      end:
        (meta.event_date_range_end as string) ||
        (meta.event_date_range_start as string) ||
        fallbackDate,
    },
    types:
      ((meta.types as string[]) || []).map(t => t.toLowerCase() as JournalType)
        .length > 0
        ? (meta.types as string[]).map(t => t.toLowerCase() as JournalType)
        : [JournalType.NOTE],
    tags: tags,
    contacts: contacts,
    calendar: meta.calendar_id
      ? {
          id: meta.calendar_id as string,
          name: 'Calendar',
          color: '#6b7280',
          is_synced_to_google: false,
        }
      : null,
    parent_id: (meta.parent_id as number) || null,
    created_at: result.attributes.created_at,
    updated_at: result.attributes.updated_at,
    highlighted,
    isSearchResult,
    highlightedTitle,
    highlightedContent,
  };
}
