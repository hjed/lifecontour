/**
 * JournalSearchCombobox component for searching and selecting journals.
 *
 * Provides a searchable combobox interface similar to ContactSearchCombobox.
 */

'use client';

import { useState, useEffect, useRef } from 'react';
import { useSearchJournals } from '@/lib/api/journals';
import { Search, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { JournalResource } from '@/types/journals';

const SEARCH_DEBOUNCE_MS = 300;
const BLUR_DELAY_MS = 200;

interface JournalSearchComboboxProps {
  readonly onSelect: (journal: JournalResource) => void;
  readonly placeholder?: string;
  readonly inputId?: string;
  readonly excludeJournalId?: string;
  readonly className?: string;
  readonly disabled?: boolean;
}

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

export function JournalSearchCombobox({
  onSelect,
  placeholder = 'Search journals...',
  inputId,
  excludeJournalId,
  className,
  disabled = false,
}: JournalSearchComboboxProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [showResults, setShowResults] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debouncedQuery = useDebounce(searchQuery, SEARCH_DEBOUNCE_MS);
  const blurTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const {
    data: searchResults,
    isLoading,
    error,
  } = useSearchJournals(
    debouncedQuery,
    { limit: 20 },
    { enabled: debouncedQuery.length > 0 }
  );

  const filteredJournals =
    searchResults?.data?.filter(journal => journal.id !== excludeJournalId) ||
    [];

  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current) {
        clearTimeout(blurTimeoutRef.current);
      }
    };
  }, []);

  const handleSelect = (journal: JournalResource) => {
    onSelect(journal);
    setSearchQuery('');
    setShowResults(false);
    setSelectedIndex(-1);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    setShowResults(value.length > 0);
    setSelectedIndex(-1);
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
            if (blurTimeoutRef.current) {
              clearTimeout(blurTimeoutRef.current);
            }
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
                {filteredJournals.map((journal, index) => {
                  const isSelected = index === selectedIndex;
                  const title = journal.attributes.title || 'Untitled Journal';

                  return (
                    <li
                      key={journal.id}
                      role='option'
                      aria-selected={isSelected}
                    >
                      <button
                        type='button'
                        className={cn(
                          'hover:bg-muted flex w-full items-center gap-2 p-3 text-left',
                          isSelected && 'bg-muted'
                        )}
                        onClick={() => handleSelect(journal)}
                      >
                        <FileText className='text-muted-foreground h-4 w-4 flex-shrink-0' />
                        <span className='truncate'>{title}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
