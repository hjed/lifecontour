'use client';

import * as React from 'react';
import { Check, ChevronsUpDown, Loader2, PlusCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useRoutes } from '@/lib/api/routes';
import { useDebounce } from '@/hooks/useDebounce';
import { RouteResource } from '@/types/routes';

export interface RouteSelectorProps {
  /** The id of the selected route */
  readonly value?: string | null;
  /** Called when a route is selected or cleared */
  readonly onChange: (routeId: string | null) => void;
  /** Disables the input */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** ID for accessibility */
  readonly id?: string;
  /** Placeholder text when nothing is selected */
  readonly placeholder?: string;
  /** aria-label for accessibility */
  readonly 'aria-label'?: string;
}

export function RouteSelector({
  value,
  onChange,
  disabled = false,
  className,
  id = 'route-selector',
  placeholder = 'Select a route...',
  'aria-label': ariaLabel,
}: RouteSelectorProps) {
  const [open, setOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');
  const debouncedSearch = useDebounce(searchQuery, 300);

  // Fetch routes based on debounced search
  const { data: routeListResponse, isLoading } = useRoutes(
    { name: debouncedSearch, limit: 10 },
    { enabled: open }
  );

  const routes: RouteResource[] = React.useMemo(
    () => routeListResponse?.data || [],
    [routeListResponse?.data]
  );
  // Find the currently selected route name if we have a value
  // Ideally, if it's an initial load and we only have an ID, we'd need to fetch that specific route,
  // but for simplicity, we assume we either have it in our search results or we'll just show 'Selected Route'
  const [selectedRouteName, setSelectedRouteName] = React.useState<
    string | null
  >(null);

  // Keep the title in sync when the route is found in the current fetch list
  React.useEffect(() => {
    if (value) {
      if (routes.length > 0) {
        const selected = routes.find(r => r.id === value);
        if (selected) {
          setSelectedRouteName(selected.attributes.name);
          return;
        }
      }
      // If we have a selected value but can't resolve its name from the current
      // results, keep showing a generic "Selected route" label instead of the placeholder.
      if (!selectedRouteName) {
        setSelectedRouteName('Selected route');
      }
    } else {
      setSelectedRouteName(null);
    }
  }, [value, routes, selectedRouteName]);

  const handleCreateNewRoute = () => {
    // In a real implementation this would navigate to a route creation modal or page
    // For now, it just closes the popover. We can expand this later.
    setOpen(false);
    // e.g. router.push('/routes/new')
  };

  return (
    <Popover
      open={open}
      onOpenChange={isOpen => {
        setOpen(isOpen);
        if (!isOpen) setSearchQuery('');
      }}
    >
      <PopoverTrigger asChild>
        <Button
          id={id}
          variant='outline'
          role='combobox'
          aria-expanded={open}
          aria-label={ariaLabel}
          disabled={disabled}
          className={cn(
            'w-full justify-between',
            !value && 'text-muted-foreground',
            className
          )}
        >
          {selectedRouteName || placeholder}
          <ChevronsUpDown className='ml-2 h-4 w-4 shrink-0 opacity-50' />
        </Button>
      </PopoverTrigger>
      <PopoverContent className='w-[300px] p-0' align='start'>
        <Command shouldFilter={false}>
          <CommandInput
            placeholder='Search routes...'
            value={searchQuery}
            onValueChange={setSearchQuery}
          />
          <CommandList>
            {isLoading && (
              <div className='flex items-center justify-center p-4'>
                <Loader2 className='text-muted-foreground h-4 w-4 animate-spin' />
                <span className='text-muted-foreground ml-2 text-sm'>
                  Loading routes...
                </span>
              </div>
            )}

            {!isLoading && routes.length === 0 && (
              <div className='py-6 text-center text-sm'>No routes found.</div>
            )}

            {!isLoading && routes.length > 0 && (
              <CommandGroup heading='Existing Routes'>
                {routes.map(route => (
                  <CommandItem
                    key={route.id}
                    value={route.id}
                    onSelect={currentValue => {
                      onChange(currentValue === value ? null : currentValue);
                      setOpen(false);
                      setSearchQuery('');
                    }}
                  >
                    <Check
                      className={cn(
                        'mr-2 h-4 w-4',
                        value === route.id ? 'opacity-100' : 'opacity-0'
                      )}
                    />
                    <div className='flex flex-col'>
                      <span>{route.attributes.name}</span>
                      {route.attributes.description && (
                        <span className='text-muted-foreground max-w-[200px] truncate text-xs'>
                          {route.attributes.description}
                        </span>
                      )}
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            <CommandSeparator />

            <CommandGroup>
              <CommandItem
                onSelect={handleCreateNewRoute}
                className='text-primary flex cursor-pointer items-center font-medium'
              >
                <PlusCircle className='mr-2 h-4 w-4' />
                Create new route...
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
