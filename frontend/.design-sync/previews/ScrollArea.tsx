import { Badge, ScrollArea, Separator } from 'lifecontour-frontend';

const ENTRIES = [
  {
    title: 'Morning run along the Yarra',
    date: '14 July 2026',
    type: 'Activity',
  },
  { title: 'Standup notes', date: '14 July 2026', type: 'Note' },
  { title: 'Coffee with Priya', date: '13 July 2026', type: 'Event' },
  { title: 'Bouldering at Northside', date: '13 July 2026', type: 'Activity' },
  { title: 'Weekend planning notes', date: '12 July 2026', type: 'Note' },
  { title: 'Long run — 18.6 km', date: '12 July 2026', type: 'Activity' },
  { title: 'Felt flat after a late night', date: '11 July 2026', type: 'Mood' },
  { title: 'Call with Sarah about Dad', date: '10 July 2026', type: 'Event' },
  { title: 'Ride to work', date: '10 July 2026', type: 'Activity' },
  { title: 'Finished "The Overstory"', date: '9 July 2026', type: 'Note' },
  { title: 'Dinner at Tom and Ellie’s', date: '8 July 2026', type: 'Event' },
  {
    title: 'Hill repeats at Studley Park',
    date: '7 July 2026',
    type: 'Activity',
  },
];

export function JournalTimeline() {
  return (
    <ScrollArea
      type='always'
      className='w-full max-w-md rounded-md border'
      style={{ height: '280px' }}
    >
      <div className='p-4'>
        <p className='mb-4 text-sm font-medium'>Recent entries</p>
        {ENTRIES.map((entry, index) => (
          <div key={entry.title}>
            {index > 0 && <Separator className='my-2' />}
            <div className='flex items-center justify-between gap-3 py-1'>
              <div className='min-w-0'>
                <p className='truncate text-sm'>{entry.title}</p>
                <p className='text-muted-foreground text-xs'>{entry.date}</p>
              </div>
              <Badge variant='outline'>{entry.type}</Badge>
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

export function TagPicker() {
  const tags = [
    'running',
    'cycling',
    'climbing',
    'catch-up',
    'work',
    'family',
    'melbourne',
    'reading',
    'health',
    'sleep',
    'travel',
    'cooking',
    'photography',
    'planning',
    'gear',
    'volunteering',
  ];

  return (
    <ScrollArea
      type='always'
      className='w-full max-w-sm rounded-md border'
      style={{ height: '200px' }}
    >
      <div className='space-y-1 p-2'>
        {tags.map(tag => (
          <div
            key={tag}
            className='flex items-center justify-between gap-2 rounded-md px-2 py-1.5'
          >
            <span className='text-sm'>{tag}</span>
            <span className='text-muted-foreground text-xs'>
              {tag.length * 7} entries
            </span>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
