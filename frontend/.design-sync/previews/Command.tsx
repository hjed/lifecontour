import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from 'lifecontour-frontend';
import {
  BookOpen,
  CalendarPlus,
  FileDown,
  MapPin,
  NotebookPen,
  User,
} from 'lucide-react';

/**
 * Global search palette. `shouldFilter={false}` mirrors the product, where
 * MeiliSearch has already ranked the results server-side — it also keeps the
 * preview deterministic while the input carries a real query.
 */
export function GlobalSearch() {
  return (
    <Command
      shouldFilter={false}
      className='rounded-lg border shadow-md'
      style={{ maxWidth: 520, margin: '0 auto' }}
    >
      <CommandInput
        value='yarra'
        onValueChange={() => {}}
        placeholder='Search journals, contacts and tags…'
      />
      <CommandList>
        <CommandGroup heading='Journals'>
          <CommandItem value='run'>
            <NotebookPen />
            <span>Morning run along the Yarra</span>
            <span className='text-muted-foreground ml-auto text-xs'>
              14 Jul 2026
            </span>
          </CommandItem>
          <CommandItem value='paddle'>
            <NotebookPen />
            <span>Paddle from Dights Falls</span>
            <span className='text-muted-foreground ml-auto text-xs'>
              2 Jul 2026
            </span>
          </CommandItem>
          <CommandItem value='series'>
            <BookOpen />
            <span>Series: Yarra Trail project</span>
            <span className='text-muted-foreground ml-auto text-xs'>
              9 entries
            </span>
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading='Contacts'>
          <CommandItem value='priya'>
            <User />
            <span>Priya Raman</span>
            <span className='text-muted-foreground ml-auto text-xs'>
              Running
            </span>
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading='Places'>
          <CommandItem value='place'>
            <MapPin />
            <span>Yarra Bend Park, Fairfield</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </Command>
  );
}

/** Zero-query state: the quick actions shown before anything is typed. */
export function QuickActions() {
  return (
    <Command
      shouldFilter={false}
      className='rounded-lg border shadow-md'
      style={{ maxWidth: 520, margin: '0 auto' }}
    >
      <CommandInput placeholder='Search journals, contacts and tags…' />
      <CommandList>
        <CommandGroup heading='Quick actions'>
          <CommandItem value='new-entry'>
            <NotebookPen />
            <span>New journal entry</span>
            <CommandShortcut>⌘N</CommandShortcut>
          </CommandItem>
          <CommandItem value='new-contact'>
            <User />
            <span>Add contact</span>
            <CommandShortcut>⌘⇧C</CommandShortcut>
          </CommandItem>
          <CommandItem value='calendar'>
            <CalendarPlus />
            <span>Connect a calendar</span>
          </CommandItem>
          <CommandItem value='export'>
            <FileDown />
            <span>Export logbook as PDF</span>
            <CommandShortcut>⇧⌘P</CommandShortcut>
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading='Recent'>
          <CommandItem value='recent-1'>
            <NotebookPen />
            <span>Werribee Gorge day walk</span>
            <span className='text-muted-foreground ml-auto text-xs'>
              5 Jul 2026
            </span>
          </CommandItem>
          <CommandItem value='recent-2'>
            <User />
            <span>Tom Nguyen</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </Command>
  );
}

/** Empty state — a query with no matches anywhere in the workspace. */
export function NoResults() {
  return (
    <Command
      shouldFilter={false}
      className='rounded-lg border shadow-md'
      style={{ maxWidth: 520, margin: '0 auto' }}
    >
      <CommandInput
        value='kayaking in kakadu'
        onValueChange={() => {}}
        placeholder='Search journals, contacts and tags…'
      />
      <CommandList>
        <CommandEmpty>
          No journals, contacts or tags match “kayaking in kakadu”.
        </CommandEmpty>
      </CommandList>
    </Command>
  );
}
