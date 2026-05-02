'use client';

import { useState, useEffect, useRef, useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Map } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import {
  ActivityTemplateResource,
  ActivityTemplateType,
} from '@/types/journals';
import { getTemplates } from '@/lib/api/templates';

const SEARCH_DEBOUNCE_MS = 300;
const BLUR_DELAY_MS = 200;

interface TemplateSelectorProps {
  readonly onSelect: (template: ActivityTemplateResource) => void;
  readonly onCreateTemplate?: () => void;
  readonly templateType: ActivityTemplateType;
  readonly placeholder?: string;
  readonly inputId?: string;
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

export function TemplateSelector({
  onSelect,
  onCreateTemplate,
  templateType,
  placeholder = 'Select a template...',
  inputId,
  className,
  disabled = false,
}: TemplateSelectorProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [showResults, setShowResults] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const debouncedQuery = useDebounce(searchQuery, SEARCH_DEBOUNCE_MS);
  const blurTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const uniqueFallbackId = useId();
  const listboxId = inputId
    ? `${inputId}-listbox`
    : `template-results-${uniqueFallbackId}`;

  // Search templates
  const {
    data: searchResults,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['templates', templateType, debouncedQuery],
    queryFn: () => getTemplates(templateType, debouncedQuery),
    // We always want to fetch templates of a certain type, even if the search query is empty.
    staleTime: 30000, // 30 seconds
  });

  const templates = searchResults?.data || [];

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current) {
        clearTimeout(blurTimeoutRef.current);
      }
    };
  }, []);

  const handleSelect = (template: ActivityTemplateResource) => {
    onSelect(template);
    setSearchQuery('');
    setShowResults(false);
    setSelectedIndex(-1);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    setShowResults(true);
    setSelectedIndex(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowResults(false);
      setSelectedIndex(-1);
      return;
    }

    if (!showResults) {
      if (e.key === 'ArrowDown') {
        setShowResults(true);
      }
      return;
    }

    const optionsCount = templates.length + (onCreateTemplate ? 1 : 0);
    if (optionsCount === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev < optionsCount - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : optionsCount - 1));
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
      e.preventDefault();
      if (selectedIndex < templates.length) {
        handleSelect(templates[selectedIndex]);
      } else if (onCreateTemplate) {
        setShowResults(false);
        onCreateTemplate();
      }
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
          onFocus={() => setShowResults(true)}
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
          aria-controls={showResults ? listboxId : undefined}
        />
      </div>

      {showResults && (
        <Card className='absolute top-full right-0 left-0 z-50 mt-1 max-h-60 overflow-auto'>
          <CardContent className='p-0'>
            {isLoading && (
              <div className='flex items-center gap-2 p-3'>
                <div className='border-primary h-4 w-4 animate-spin rounded-full border-2 border-t-transparent' />
                <span>Loading templates...</span>
              </div>
            )}

            {error && (
              <div className='text-destructive p-3'>
                <span>Error loading templates</span>
              </div>
            )}

            {!isLoading && !error && templates.length === 0 && (
              <div className='text-muted-foreground p-3'>
                <span>No templates found</span>
              </div>
            )}

            {!isLoading && !error && (
              <ul id={listboxId} role='listbox' className='m-0 list-none p-0'>
                {templates.map((template, index) => {
                  const isSelected = index === selectedIndex;
                  return (
                    <li
                      key={template.id}
                      role='option'
                      aria-selected={isSelected}
                    >
                      <button
                        type='button'
                        className={cn(
                          'hover:bg-muted flex w-full items-center gap-2 p-3 text-left',
                          isSelected && 'bg-muted'
                        )}
                        onClick={() => handleSelect(template)}
                      >
                        <Map className='text-muted-foreground h-4 w-4' />
                        <span className='flex flex-col'>
                          <span>{template.attributes.name}</span>
                          {template.attributes.region && (
                            <span className='text-muted-foreground text-xs'>
                              {template.attributes.region}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
                {onCreateTemplate && (
                  <li
                    role='option'
                    aria-selected={selectedIndex === templates.length}
                    className='border-t'
                  >
                    <button
                      type='button'
                      className={cn(
                        'hover:bg-muted text-primary flex w-full items-center gap-2 p-3 text-left font-medium',
                        selectedIndex === templates.length && 'bg-muted'
                      )}
                      onClick={() => {
                        setShowResults(false);
                        onCreateTemplate();
                      }}
                    >
                      <span>+ Create new template</span>
                    </button>
                  </li>
                )}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
