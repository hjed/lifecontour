/**
 * JournalSearchCombobox component for searching and selecting parent journals.
 *
 * Provides a searchable combobox interface for selecting parent journals with
 * debounced search, keyboard navigation, and proper accessibility.
 * Uses the existing GET /api/journals?search= endpoint.
 */

'use client';

import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Book } from 'lucide-react';
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { JournalResource, JournalListResponse } from '@/types/journals';
import { API_ENDPOINTS } from '@/lib/constants';

// Constants
const SEARCH_DEBOUNCE_MS = 300;
const BLUR_DELAY_MS = 200; // Delay to prevent dropdown from closing before click events are processed

interface JournalSearchComboboxProps {
  readonly onSelect: (journal: JournalResource) => void;
  readonly onClear?: () => void;
  readonly onSearchChange?: (query: string) => void;
  readonly placeholder?: string;
  readonly inputId?: string;
  readonly excludeJournalId?: string;
  readonly value?: string; // Currently selected title (optional)
  readonly className?: string;
  readonly disabled?: boolean;
}

// Debounce hook
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

// Search journals API function
async function searchJournals(query: string): Promise<JournalListResponse> {
  if (!query.trim()) {
    return { data: [], meta: { total: 0, page: 1, size: 20, pages: 1 } };
  }

  const response = await fetch(
    `${API_ENDPOINTS.JOURNALS.BASE}?search=${encodeURIComponent(query)}&limit=20`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    throw new Error('Failed to search journals');
  }

  return response.json();
}

export function JournalSearchCombobox({
  onSelect,
  onClear,
  onSearchChange,
  placeholder = 'Search journals...',
  inputId,
  excludeJournalId,
  value = '',
  className,
  disabled = false,
}: JournalSearchComboboxProps) {
  const [searchQuery, setSearchQuery] = useState(value);
  const [showResults, setShowResults] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debouncedQuery = useDebounce(searchQuery, SEARCH_DEBOUNCE_MS);
  const blurTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Sync searchQuery when the value prop changes externally (e.g., edit flow)
  useEffect(() => {
    setSearchQuery(value);
  }, [value]);

  // Search query
  const {
    data: searchResults,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['journals', 'search', debouncedQuery],
    queryFn: () => searchJournals(debouncedQuery),
    enabled: debouncedQuery.length > 0,
    staleTime: 30000, // 30 seconds
  });

  // Filter out excluded journal (to prevent self-cycles)
  const filteredJournals =
    searchResults?.data?.filter(
      (journal: JournalResource) => String(journal.id) !== excludeJournalId
    ) || [];

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current) {
        clearTimeout(blurTimeoutRef.current);
      }
    };
  }, []);

  const handleSelect = (journal: JournalResource) => {
    onSelect(journal);
    setSearchQuery(journal.attributes.title);
    setShowResults(false);
    setSelectedIndex(-1);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    setShowResults(value.length > 0);
    setSelectedIndex(-1);
    // Notify consumer of user-initiated input changes
    onSearchChange?.(value);
    // If the user clears the input, notify the parent so it can reset
    // its stored selection (e.g. parentId) to stay in sync.
    if (!value && onClear) {
      onClear();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowResults(false);
      setSelectedIndex(-1);
      return;
    }

    if (!showResults || filteredJournals.length === 0) {
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev =>
        prev < filteredJournals.length - 1 ? prev + 1 : 0
      );
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev =>
        prev > 0 ? prev - 1 : filteredJournals.length - 1
      );
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      handleSelect(filteredJournals[selectedIndex]);
    }
  };

  return (
    <div className={cn('relative w-full', className)}>
      <div className='relative'>
        <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
        <Input
          id={inputId}
          type='text'
          placeholder={placeholder}
          value={searchQuery}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => searchQuery && setShowResults(true)}
          onBlur={() => {
            // Clear any existing timeout
            if (blurTimeoutRef.current) {
              clearTimeout(blurTimeoutRef.current);
            }
            // Set new timeout
            blurTimeoutRef.current = setTimeout(
              () => setShowResults(false),
              BLUR_DELAY_MS
            );
          }}
          className='pl-10'
          disabled={disabled}
          autoComplete='off'
          role='combobox'
          aria-expanded={showResults}
          aria-haspopup='listbox'
          aria-controls={showResults ? 'journal-search-results' : undefined}
        />
      </div>

      {showResults && (debouncedQuery.length > 0 || isLoading) && (
        <Card className='absolute top-full right-0 left-0 z-50 mt-1 max-h-60 overflow-auto'>
          <CardContent className='p-0'>
            {isLoading && (
              <div className='flex items-center gap-2 p-3'>
                <div className='border-primary h-4 w-4 animate-spin rounded-full border-2 border-t-transparent' />
                <span>Searching...</span>
              </div>
            )}

            {error && (
              <div className='text-destructive p-3'>
                <span>Error searching journals</span>
              </div>
            )}

            {!isLoading &&
              !error &&
              filteredJournals.length === 0 &&
              debouncedQuery && (
                <div className='text-muted-foreground p-3'>
                  <span>No journals found</span>
                </div>
              )}

            {!isLoading && !error && filteredJournals.length > 0 && (
              <ul
                id='journal-search-results'
                role='listbox'
                className='m-0 list-none p-0'
              >
                {filteredJournals.map(
                  (journal: JournalResource, index: number) => {
                    const isSelected = index === selectedIndex;
                    return (
                      <li
                        key={journal.id}
                        role='option'
                        aria-selected={isSelected}
                      >
                        <button
                          type='button'
                          className={cn(
                            'hover:bg-muted flex w-full flex-col items-start gap-1 p-3 text-left',
                            isSelected && 'bg-muted'
                          )}
                          onClick={() => handleSelect(journal)}
                        >
                          <div className='flex w-full items-center gap-2'>
                            <Book className='text-muted-foreground h-4 w-4 shrink-0' />
                            <span className='flex-1 truncate font-medium'>
                              {journal.attributes.title}
                            </span>
                            <span className='text-muted-foreground shrink-0 text-xs'>
                              {format(
                                parseISO(
                                  journal.attributes.event_date_range.start
                                ),
                                'MMM d, yyyy'
                              )}
                            </span>
                          </div>
                        </button>
                      </li>
                    );
                  }
                )}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
