/**
 * ContactSearchCombobox component for searching and selecting contacts.
 *
 * Provides a searchable combobox interface for selecting contacts with
 * debounced search, keyboard navigation, and proper accessibility.
 */

'use client';

import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, User } from 'lucide-react';
import { cn, generateDisplayName } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { ContactResource, ContactListResponse } from '@/types/contacts';
import { API_ENDPOINTS } from '@/lib/constants';

// Constants
const SEARCH_DEBOUNCE_MS = 300;
const BLUR_DELAY_MS = 200; // Delay to prevent dropdown from closing before click events are processed

interface ContactSearchComboboxProps {
  onSelect: (contact: ContactResource) => void;
  placeholder?: string;
  excludeContactId?: string;
  className?: string;
  disabled?: boolean;
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

// Search contacts API function
async function searchContacts(query: string): Promise<ContactListResponse> {
  if (!query.trim()) {
    return { data: [] };
  }

  const response = await fetch(
    `${API_ENDPOINTS.CONTACTS.BASE}?search=${encodeURIComponent(query)}&limit=20`,
    {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    throw new Error('Failed to search contacts');
  }

  return response.json();
}

export function ContactSearchCombobox({
  onSelect,
  placeholder = 'Search contacts...',
  excludeContactId,
  className,
  disabled = false,
}: ContactSearchComboboxProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [showResults, setShowResults] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debouncedQuery = useDebounce(searchQuery, SEARCH_DEBOUNCE_MS);

  // Search query
  const {
    data: searchResults,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['contacts', 'search', debouncedQuery],
    queryFn: () => searchContacts(debouncedQuery),
    enabled: debouncedQuery.length > 0,
    staleTime: 30000, // 30 seconds
  });

  // Filter out excluded contact
  const filteredContacts = searchResults?.data?.filter(
    contact => contact.id !== excludeContactId
  ) || [];

  const handleSelect = (contact: ContactResource) => {
    onSelect(contact);
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

    if (!showResults || filteredContacts.length === 0) {
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev =>
        prev < filteredContacts.length - 1 ? prev + 1 : 0
      );
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev =>
        prev > 0 ? prev - 1 : filteredContacts.length - 1
      );
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      handleSelect(filteredContacts[selectedIndex]);
    }
  };

  return (
    <div className={cn('relative w-full', className)}>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="text"
          placeholder={placeholder}
          value={searchQuery}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => searchQuery && setShowResults(true)}
          onBlur={() => setTimeout(() => setShowResults(false), BLUR_DELAY_MS)}
          className="pl-10"
          disabled={disabled}
          role="combobox"
          aria-expanded={showResults}
          aria-haspopup="listbox"
        />
      </div>

      {showResults && (debouncedQuery.length > 0 || isLoading) && (
        <Card className="absolute top-full left-0 right-0 z-50 mt-1 max-h-60 overflow-auto">
          <CardContent className="p-0">
            {isLoading && (
              <div className="flex items-center gap-2 p-3">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <span>Searching...</span>
              </div>
            )}

            {error && (
              <div className="p-3 text-destructive">
                <span>Error searching contacts</span>
              </div>
            )}

            {!isLoading && !error && filteredContacts.length === 0 && debouncedQuery && (
              <div className="p-3 text-muted-foreground">
                <span>No contacts found</span>
              </div>
            )}

            {!isLoading && !error && filteredContacts.length > 0 && (
              <div role="listbox">
                {filteredContacts.map((contact, index) => {
                  const displayName = generateDisplayName(
                    contact.attributes.first_name,
                    contact.attributes.last_name || ''
                  );

                  // Add nickname in parentheses if present
                  const fullDisplayName = contact.attributes.nick_name?.trim()
                    ? `${displayName} (${contact.attributes.nick_name})`
                    : displayName;

                  const isSelected = index === selectedIndex;

                  return (
                    <button
                      key={contact.id}
                      type="button"
                      className={cn(
                        "flex w-full items-center gap-2 p-3 text-left hover:bg-muted",
                        isSelected && "bg-muted"
                      )}
                      onClick={() => handleSelect(contact)}
                      role="option"
                      aria-selected={isSelected}
                    >
                      <User className="h-4 w-4 text-muted-foreground" />
                      <span>{fullDisplayName}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
