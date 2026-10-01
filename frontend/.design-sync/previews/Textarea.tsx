import { Label, Textarea } from 'lifecontour-frontend';

export function Basic() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='entry-notes'>Notes</Label>
      <Textarea
        id='entry-notes'
        rows={4}
        defaultValue={
          '8.2 km along the Yarra before work. Cool morning, legs felt good after the rest day.'
        }
      />
    </div>
  );
}

export function WithDescription() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='contact-context'>How you met</Label>
      <Textarea
        id='contact-context'
        rows={3}
        placeholder='Met Priya at the Carlton running club in March 2026…'
      />
      <p className='text-muted-foreground text-sm'>
        Shown at the top of the contact page. Supports plain text only.
      </p>
    </div>
  );
}

export function Invalid() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='entry-summary' className='text-destructive'>
        Summary
      </Label>
      <Textarea
        id='entry-summary'
        rows={3}
        aria-invalid='true'
        aria-describedby='entry-summary-error'
        defaultValue='Coffee'
      />
      <p id='entry-summary-error' className='text-destructive text-sm'>
        Summary must be at least 20 characters.
      </p>
    </div>
  );
}

export function Disabled() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='strava-description'>Activity description</Label>
      <Textarea
        id='strava-description'
        rows={3}
        disabled
        defaultValue={'Morning Run — 8.2 km, 42:10, 5:08 /km average pace.'}
      />
      <p className='text-muted-foreground text-sm'>
        Read-only while the Strava integration owns this entry.
      </p>
    </div>
  );
}
