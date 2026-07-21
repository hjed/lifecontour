import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Separator,
} from 'personal-management-frontend';
import { ChevronDown, ChevronRight } from 'lucide-react';

export function Expanded() {
  return (
    <Collapsible defaultOpen className='max-w-md space-y-2'>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-sm font-medium'>Linked contacts (3)</p>
        <CollapsibleTrigger asChild>
          <Button variant='ghost' size='sm'>
            <ChevronDown />
            Hide
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className='space-y-2'>
        {['Priya Raman', 'Tom Whitfield', 'Sarah Nguyen'].map(name => (
          <div
            key={name}
            className='flex items-center justify-between gap-2 rounded-md border px-3 py-2'
          >
            <span className='text-sm'>{name}</span>
            <Badge variant='secondary'>mentioned</Badge>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function Collapsed() {
  return (
    <Collapsible className='max-w-md space-y-2'>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-sm font-medium'>Linked contacts (3)</p>
        <CollapsibleTrigger asChild>
          <Button variant='ghost' size='sm'>
            <ChevronRight />
            Show
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className='space-y-2'>
        {['Priya Raman', 'Tom Whitfield', 'Sarah Nguyen'].map(name => (
          <div
            key={name}
            className='flex items-center justify-between gap-2 rounded-md border px-3 py-2'
          >
            <span className='text-sm'>{name}</span>
            <Badge variant='secondary'>mentioned</Badge>
          </div>
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function EntryHistory() {
  const revisions = [
    { when: '14 July 2026, 6:52 am', what: 'Added tag “health”' },
    { when: '14 July 2026, 6:48 am', what: 'Linked activity from Strava' },
    { when: '14 July 2026, 6:41 am', what: 'Entry created' },
  ];

  return (
    <Card className='max-w-md'>
      <CardHeader>
        <CardTitle>Morning run</CardTitle>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-sm'>
          8.2 km along the Yarra before work. Quickest split of the month.
        </p>
        <Separator />
        <Collapsible defaultOpen className='space-y-2'>
          <CollapsibleTrigger asChild>
            <Button variant='outline' size='sm' className='w-full'>
              <ChevronDown />
              Change history
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className='space-y-2'>
            {revisions.map(revision => (
              <div key={revision.when} className='space-y-0.5'>
                <p className='text-sm'>{revision.what}</p>
                <p className='text-muted-foreground text-xs'>{revision.when}</p>
              </div>
            ))}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}
