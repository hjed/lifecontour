'use client';

/**
 * Global search component for the header.
 *
 * Provides a search input with suggestions dropdown, connecting to the global search API.
 * Features include:
 * - Real-time search suggestions
 * - Keyboard navigation
 * - Recent searches
 * - Quick filters
 * - Responsive design
 */

import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
  useId,
} from 'react';
import { Search, X, Clock, Filter } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/useDebounce';

interface GlobalSearchProps {
  /** Additional CSS classes */
  readonly className?: string;
  /** Placeholder text for the search input */
  readonly placeholder?: string;
  /** Whether to show the search suggestions dropdown */
  readonly showSuggestions?: boolean;
  /** Callback when search is performed */
  readonly onSearch?: (query: string) => void;
}

interface SearchSuggestion {
  id: string;
  text: string;
  type: 'contact' | 'recent' | 'filter';
  icon?: React.ReactNode;
  url?: string;
}

// Mock data for suggestions - will be replaced with real API calls
const mockSuggestions: SearchSuggestion[] = [
  { id: '1', text: 'John Smith', type: 'contact', url: '/contacts/1' },
  { id: '2', text: 'Jane Doe', type: 'contact', url: '/contacts/2' },
  {
    id: '3',
    text: 'meeting notes',
    type: 'recent',
    icon: <Clock className='h-3 w-3' />,
  },
  {
    id: '4',
    text: 'favourites',
    type: 'filter',
    icon: <Filter className='h-3 w-3' />,
    url: '/contacts/favourites',
  },
];

export function GlobalSearch({
  className,
  placeholder = 'Search contacts, journals...',
  showSuggestions = true,
  onSearch,
}: GlobalSearchProps) {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  // Load recent searches from localStorage using lazy initialization
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    if (globalThis.window === undefined) return [];
    const saved = localStorage.getItem('recent-searches');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        return [];
      }
    }
    return [];
  });

  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Generate unique IDs for accessibility
  const uniqueId = useId();
  const listboxId = `search-listbox-${uniqueId}`;
  const getOptionId = (index: number) => `search-option-${listboxId}-${index}`;

  // Debounce search query for API calls
  const debouncedQuery = useDebounce(query, 300);

  // Save recent searches to localStorage
  const saveRecentSearch = useCallback(
    (searchQuery: string) => {
      if (!searchQuery.trim()) return;

      const updated = [
        searchQuery,
        ...recentSearches.filter(s => s !== searchQuery),
      ].slice(0, 5);
      setRecentSearches(updated);
      localStorage.setItem('recent-searches', JSON.stringify(updated));
    },
    [recentSearches]
  );

  // Handle search submission
  const handleSearch = useCallback(
    (searchQuery: string = query) => {
      const trimmedQuery = searchQuery.trim();
      if (!trimmedQuery) return;

      saveRecentSearch(trimmedQuery);
      setIsOpen(false);
      setQuery('');

      // Navigate to search results page or call callback
      if (onSearch) {
        onSearch(trimmedQuery);
      } else {
        // TODO: ITER1.5-001 - Implement navigation to search results page
        // router.push(`/search?q=${encodeURIComponent(trimmedQuery)}`);
        console.log('Search query:', trimmedQuery);
      }
    },
    [query, onSearch, saveRecentSearch]
  );

  // Handle input changes
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);
    setSelectedIndex(-1);

    if (value.length > 0 && showSuggestions) {
      setIsOpen(true);
    } else {
      setIsOpen(false);
    }
  };

  // Memoize suggestions to prevent unnecessary recalculations
  const suggestions = useMemo(() => {
    if (!debouncedQuery.trim()) {
      // Show recent searches when no query
      return recentSearches.map((search, index) => ({
        id: `recent-${index}`,
        text: search,
        type: 'recent' as const,
        icon: <Clock className='h-3 w-3' />,
        url: undefined, // Recent searches don't have URLs
      }));
    }

    // Filter mock suggestions based on query
    return mockSuggestions.filter(suggestion =>
      suggestion.text.toLowerCase().includes(debouncedQuery.toLowerCase())
    );
  }, [debouncedQuery, recentSearches]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!isOpen) {
        if (e.key === 'Enter') {
          handleSearch();
        }
        return;
      }

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex(prev => (prev + 1) % suggestions.length);
          break;
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex(prev =>
            prev <= 0 ? suggestions.length - 1 : prev - 1
          );
          break;
        case 'Enter':
          e.preventDefault();
          if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
            const suggestion = suggestions[selectedIndex];
            if (suggestion.url) {
              // TODO: ITER1.5-001 - Implement proper navigation to suggestion URLs
              // router.push(suggestion.url);
              console.log('Navigate to:', suggestion.url);
              setIsOpen(false);
              setQuery('');
            } else {
              handleSearch(suggestion.text);
            }
          } else {
            handleSearch();
          }
          break;
        case 'Escape':
          setIsOpen(false);
          setSelectedIndex(-1);
          inputRef.current?.blur();
          break;
      }
    },
    [isOpen, handleSearch, suggestions, selectedIndex]
  );

  // Handle clicking outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        !inputRef.current?.contains(event.target as Node)
      ) {
        setIsOpen(false);
        setSelectedIndex(-1);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className={cn('relative w-full max-w-md', className)}>
      {/* Search Input */}
      <div className='relative'>
        <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
        <Input
          ref={inputRef}
          type='text'
          placeholder={placeholder}
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => showSuggestions && setIsOpen(true)}
          className='pr-10 pl-10'
          aria-label='Global search'
          aria-expanded={isOpen}
          aria-haspopup='listbox'
          aria-autocomplete='list'
          aria-controls={isOpen ? listboxId : undefined}
          aria-activedescendant={
            isOpen && selectedIndex >= 0
              ? getOptionId(selectedIndex)
              : undefined
          }
          role='combobox'
        />
        {query && (
          <Button
            variant='ghost'
            size='sm'
            className='absolute top-1/2 right-1 h-6 w-6 -translate-y-1/2 p-0'
            onClick={() => {
              setQuery('');
              setIsOpen(false);
              inputRef.current?.focus();
            }}
            aria-label='Clear search'
          >
            <X className='h-3 w-3' />
          </Button>
        )}
      </div>

      {/* Suggestions Dropdown */}
      {isOpen && showSuggestions && suggestions.length > 0 && (
        <Card
          ref={dropdownRef}
          className='absolute top-full right-0 left-0 z-50 mt-1 max-h-80 overflow-auto'
        >
          <CardContent className='p-0'>
            <div role='listbox' aria-label='Search suggestions' id={listboxId}>
              {!debouncedQuery.trim() && recentSearches.length > 0 && (
                <>
                  <div className='text-muted-foreground px-3 py-2 text-xs font-medium'>
                    Recent searches
                  </div>
                  <Separator />
                </>
              )}

              {suggestions.map((suggestion, index) => (
                <button
                  key={suggestion.id}
                  id={getOptionId(index)}
                  className={cn(
                    'hover:bg-accent flex w-full items-center gap-2 px-3 py-2 text-left text-sm',
                    selectedIndex === index && 'bg-accent'
                  )}
                  onClick={() => {
                    if (suggestion.url) {
                      // TODO: ITER1.5-001 - Implement proper navigation to suggestion URLs
                      // router.push(suggestion.url);
                      console.log('Navigate to:', suggestion.url);
                      setIsOpen(false);
                      setQuery('');
                    } else {
                      handleSearch(suggestion.text);
                    }
                  }}
                  role='option'
                  aria-selected={selectedIndex === index}
                >
                  {suggestion.icon && (
                    <span className='text-muted-foreground'>
                      {suggestion.icon}
                    </span>
                  )}
                  <span className='flex-1'>{suggestion.text}</span>
                  {suggestion.type === 'filter' && (
                    <Badge variant='secondary' className='text-xs'>
                      Filter
                    </Badge>
                  )}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
