import { Label, RadioGroup, RadioGroupItem } from 'lifecontour-frontend';

export function EntryType() {
  return (
    <div className='flex max-w-sm flex-col gap-3'>
      <p className='text-sm font-medium'>Entry type</p>
      <RadioGroup defaultValue='note'>
        <div className='flex items-center gap-2'>
          <RadioGroupItem value='note' id='entry-type-note' />
          <Label htmlFor='entry-type-note'>Note</Label>
        </div>
        <div className='flex items-center gap-2'>
          <RadioGroupItem value='event' id='entry-type-event' />
          <Label htmlFor='entry-type-event'>Event</Label>
        </div>
        <div className='flex items-center gap-2'>
          <RadioGroupItem value='mood' id='entry-type-mood' />
          <Label htmlFor='entry-type-mood'>Mood rating</Label>
        </div>
      </RadioGroup>
    </div>
  );
}

export function WithDescriptions() {
  return (
    <div className='flex max-w-sm flex-col gap-3'>
      <p className='text-sm font-medium'>Export range</p>
      <RadioGroup defaultValue='month' className='gap-4'>
        <div className='flex items-start gap-2'>
          <RadioGroupItem value='month' id='range-month' className='mt-1' />
          <div className='flex flex-col gap-2'>
            <Label htmlFor='range-month'>This month</Label>
            <p className='text-muted-foreground text-sm'>
              1 – 31 July 2026, 42 entries.
            </p>
          </div>
        </div>
        <div className='flex items-start gap-2'>
          <RadioGroupItem value='year' id='range-year' className='mt-1' />
          <div className='flex flex-col gap-2'>
            <Label htmlFor='range-year'>This year</Label>
            <p className='text-muted-foreground text-sm'>
              1 January – 21 July 2026, 388 entries.
            </p>
          </div>
        </div>
        <div className='flex items-start gap-2'>
          <RadioGroupItem value='all' id='range-all' className='mt-1' />
          <div className='flex flex-col gap-2'>
            <Label htmlFor='range-all'>Everything</Label>
            <p className='text-muted-foreground text-sm'>
              Every entry since 3 February 2021.
            </p>
          </div>
        </div>
      </RadioGroup>
    </div>
  );
}

export function Horizontal() {
  return (
    <div className='flex max-w-sm flex-col gap-3'>
      <p className='text-sm font-medium'>Mood today</p>
      <RadioGroup defaultValue='4' className='flex items-center gap-6'>
        {['1', '2', '3', '4', '5'].map(value => (
          <div key={value} className='flex items-center gap-2'>
            <RadioGroupItem value={value} id={`mood-${value}`} />
            <Label htmlFor={`mood-${value}`}>{value}</Label>
          </div>
        ))}
      </RadioGroup>
    </div>
  );
}

export function Disabled() {
  return (
    <div className='flex max-w-sm flex-col gap-3'>
      <p className='text-sm font-medium'>Sync direction</p>
      <RadioGroup defaultValue='pull' disabled>
        <div className='flex items-center gap-2'>
          <RadioGroupItem value='pull' id='sync-pull' />
          <Label htmlFor='sync-pull'>Pull from Strava</Label>
        </div>
        <div className='flex items-center gap-2'>
          <RadioGroupItem value='push' id='sync-push' />
          <Label htmlFor='sync-push'>Push to Strava</Label>
        </div>
      </RadioGroup>
      <p className='text-muted-foreground text-sm'>
        Locked while a sync is running.
      </p>
    </div>
  );
}
