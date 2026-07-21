import {
  Badge,
  Button,
  Checkbox,
  Label,
  Separator,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from 'personal-management-frontend';
import { GitMerge, Zap } from 'lucide-react';

const reviewItems = [
  {
    id: 'dup-1',
    icon: 'merge' as const,
    title: 'Possible duplicate',
    entry: 'Coffee with Priya — 14 July 2026',
    detail: 'Looks like the same catch-up as “Coffee, Fitzroy” (92% match).',
  },
  {
    id: 'act-1',
    icon: 'zap' as const,
    title: 'Unmatched activity',
    entry: 'Strava ride, 42.6 km — 12 July 2026',
    detail: 'No journal entry covers this ride. Create one from the activity?',
  },
];

/**
 * Right-hand review queue — ported from ReviewQueueSidebar, the app's real
 * Sheet. Forced open with `modal={false}` so the static capture keeps the
 * overlay without the scroll-lock artefacts of a modal layer.
 */
export function ReviewQueue() {
  return (
    <Sheet open modal={false}>
      <SheetContent
        className='w-full overflow-y-auto sm:max-w-md'
        onOpenAutoFocus={e => e.preventDefault()}
      >
        <SheetHeader>
          <SheetTitle className='flex items-center gap-2'>
            Review queue
            <Badge variant='destructive' className='font-mono'>
              2
            </Badge>
          </SheetTitle>
          <SheetDescription>
            Suggestions for journals that may be duplicates or that are missing
            a linked activity.
          </SheetDescription>
        </SheetHeader>

        <div className='flex flex-col gap-3 px-4'>
          {reviewItems.map(item => (
            <div key={item.id} className='rounded-md border p-3'>
              <div className='flex items-center gap-2'>
                {item.icon === 'merge' ? (
                  <GitMerge className='text-muted-foreground h-4 w-4' />
                ) : (
                  <Zap className='text-muted-foreground h-4 w-4' />
                )}
                <span className='text-sm font-medium'>{item.title}</span>
              </div>
              <p className='mt-2 text-sm font-medium'>{item.entry}</p>
              <p className='text-muted-foreground mt-1 text-sm'>
                {item.detail}
              </p>
              <div className='mt-2 flex gap-2'>
                <Button size='sm'>Resolve</Button>
                <Button size='sm' variant='ghost'>
                  Dismiss
                </Button>
              </div>
            </div>
          ))}
        </div>

        <SheetFooter>
          <Separator />
          <Button variant='outline' className='w-full'>
            Dismiss all suggestions
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

const journalTypes = [
  { id: 'note', label: 'Note', checked: true },
  { id: 'event', label: 'Event', checked: true },
  { id: 'mood', label: 'Mood rating', checked: false },
  { id: 'gear', label: 'Gear usage', checked: false },
];

/** Left-side filter panel — the same Sheet with `side="left"`. */
export function FilterPanel() {
  return (
    <Sheet open modal={false}>
      <SheetContent
        side='left'
        className='w-full sm:max-w-sm'
        onOpenAutoFocus={e => e.preventDefault()}
      >
        <SheetHeader>
          <SheetTitle>Filter journals</SheetTitle>
          <SheetDescription>
            Showing 128 entries from 1 January 2026 to today.
          </SheetDescription>
        </SheetHeader>

        <div className='flex flex-col gap-4 px-4'>
          <div className='flex flex-col gap-3'>
            <span className='text-sm font-medium'>Entry type</span>
            {journalTypes.map(t => (
              <div key={t.id} className='flex items-center gap-2'>
                <Checkbox id={`type-${t.id}`} defaultChecked={t.checked} />
                <Label htmlFor={`type-${t.id}`} className='font-normal'>
                  {t.label}
                </Label>
              </div>
            ))}
          </div>
          <Separator />
          <div className='flex flex-col gap-2'>
            <span className='text-sm font-medium'>Tags</span>
            <div className='flex flex-wrap gap-2'>
              <Badge variant='secondary'>Bushwalking</Badge>
              <Badge variant='secondary'>Family</Badge>
              <Badge variant='outline'>Work</Badge>
              <Badge variant='outline'>Cycling</Badge>
            </div>
          </div>
        </div>

        <SheetFooter>
          <Button className='w-full'>Apply filters</Button>
          <Button variant='ghost' className='w-full'>
            Reset
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
