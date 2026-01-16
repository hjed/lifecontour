/**
 * Tests for useDisplayJournals hook
 */

import { renderHook } from '@testing-library/react';
import { useDisplayJournals } from '../useDisplayJournals';
import { JournalResource, JournalType } from '@/types/journals';

describe('useDisplayJournals', () => {
  const mockJournal: JournalResource = {
    type: 'journals',
    id: '1',
    attributes: {
      title: 'Test Journal',
      content: 'This is test content',
      event_date_range: {
        start: '2024-01-01T00:00:00Z',
        end: '2024-01-01T23:59:59Z',
      },
      types: [JournalType.NOTE],
      contacts: [],
      tags: [],
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
  };

  const mockJournalWithHighlighting: JournalResource = {
    ...mockJournal,
    meta: {
      highlighted: {
        title: '<mark>Test</mark> Journal',
        content: 'This is <mark>test</mark> content',
      },
    },
  };

  it('returns empty array when journals is undefined', () => {
    const { result } = renderHook(() => useDisplayJournals(undefined));
    expect(result.current).toEqual([]);
  });

  it('returns empty array when journals is empty', () => {
    const { result } = renderHook(() => useDisplayJournals([]));
    expect(result.current).toEqual([]);
  });

  it('transforms journal data correctly without search highlighting', () => {
    const { result } = renderHook(() => useDisplayJournals([mockJournal]));

    const displayJournal = result.current[0];

    expect(displayJournal.id).toBe('1');
    expect(displayJournal.title).toBe('Test Journal');
    expect(displayJournal.content).toBe('This is test content');
    expect(displayJournal.event_date_range).toEqual({
      start: '2024-01-01T00:00:00Z',
      end: '2024-01-01T23:59:59Z',
    });
    expect(displayJournal.types).toEqual([JournalType.NOTE]);
    expect(displayJournal.isSearchResult).toBe(false);
    expect(displayJournal.highlightedTitle).toBeNull();
    expect(displayJournal.highlightedContent).toBeNull();
  });

  it('handles search highlighting when shouldUseSearch is true', () => {
    const { result } = renderHook(() =>
      useDisplayJournals([mockJournalWithHighlighting], true)
    );

    const displayJournal = result.current[0];

    expect(displayJournal.isSearchResult).toBe(true);
    expect(displayJournal.highlighted).toEqual({
      title: '<mark>Test</mark> Journal',
      content: 'This is <mark>test</mark> content',
    });
    expect(displayJournal.highlightedTitle).toBe('<mark>Test</mark> Journal');
    expect(displayJournal.highlightedContent).toBe(
      'This is <mark>test</mark> content'
    );
  });

  it('does not include search highlighting when shouldUseSearch is false', () => {
    const { result } = renderHook(() =>
      useDisplayJournals([mockJournalWithHighlighting], false)
    );

    const displayJournal = result.current[0];

    expect(displayJournal.isSearchResult).toBe(false);
    expect(displayJournal.highlighted).toEqual({
      title: '<mark>Test</mark> Journal',
      content: 'This is <mark>test</mark> content',
    });
    expect(displayJournal.highlightedTitle).toBeNull();
    expect(displayJournal.highlightedContent).toBeNull();
  });

  it('handles journal with highlighting but missing highlighted fields', () => {
    const journalWithPartialHighlighting: JournalResource = {
      ...mockJournal,
      meta: {
        highlighted: {
          title: '<mark>Test</mark> Journal',
          // Missing content
        },
      },
    };

    const { result } = renderHook(() =>
      useDisplayJournals([journalWithPartialHighlighting], true)
    );

    const displayJournal = result.current[0];

    expect(displayJournal.isSearchResult).toBe(true);
    expect(displayJournal.highlightedTitle).toBe('<mark>Test</mark> Journal');
    expect(displayJournal.highlightedContent).toBeNull();
  });

  it('handles journal without meta.highlighted when shouldUseSearch is true', () => {
    const { result } = renderHook(() =>
      useDisplayJournals([mockJournal], true)
    );

    const displayJournal = result.current[0];

    expect(displayJournal.isSearchResult).toBe(false);
    expect(displayJournal.highlighted).toBeUndefined();
    expect(displayJournal.highlightedTitle).toBeNull();
    expect(displayJournal.highlightedContent).toBeNull();
  });

  it('updates when dependencies change', () => {
    const { result, rerender } = renderHook(
      ({ journals, shouldUseSearch }) =>
        useDisplayJournals(journals, shouldUseSearch),
      {
        initialProps: { journals: [mockJournal], shouldUseSearch: false },
      }
    );

    const firstResult = result.current;
    expect(firstResult[0].isSearchResult).toBe(false);

    // Rerender with different shouldUseSearch - should update the result
    rerender({
      journals: [mockJournalWithHighlighting],
      shouldUseSearch: true,
    });
    expect(result.current[0].isSearchResult).toBe(true);
    expect(result.current[0].highlightedTitle).toBe(
      '<mark>Test</mark> Journal'
    );
  });
});
