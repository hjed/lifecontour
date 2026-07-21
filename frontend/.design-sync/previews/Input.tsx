import { Input, Label } from 'personal-management-frontend';
import { Search } from 'lucide-react';

export function Basic() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='entry-title'>Entry title</Label>
      <Input id='entry-title' placeholder='Morning run along the Yarra' />
    </div>
  );
}

export function Types() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='contact-email'>Email</Label>
        <Input
          id='contact-email'
          type='email'
          defaultValue='priya.raman@example.com.au'
        />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='entry-date'>Entry date</Label>
        <Input id='entry-date' type='date' defaultValue='2026-07-14' />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='run-distance'>Distance (km)</Label>
        <Input id='run-distance' type='number' step='0.1' defaultValue='8.2' />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='journal-search'>Search journals</Label>
        <div style={{ position: 'relative' }}>
          <Search
            aria-hidden='true'
            className='text-muted-foreground size-4'
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
            }}
          />
          <Input
            id='journal-search'
            type='search'
            className='pl-8'
            placeholder='Coffee with Priya'
          />
        </div>
      </div>
    </div>
  );
}

export function Invalid() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='contact-phone' className='text-destructive'>
        Mobile number
      </Label>
      <Input
        id='contact-phone'
        aria-invalid='true'
        aria-describedby='contact-phone-error'
        defaultValue='04123'
      />
      <p id='contact-phone-error' className='text-destructive text-sm'>
        Enter a valid Australian mobile, e.g. 0412 345 678.
      </p>
    </div>
  );
}

export function Disabled() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='strava-id'>Strava activity ID</Label>
        <Input id='strava-id' disabled defaultValue='14829301774' />
        <p className='text-muted-foreground text-sm'>
          Synced from Strava and cannot be edited here.
        </p>
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='created-at'>Created</Label>
        <Input id='created-at' readOnly defaultValue='14 July 2026, 6:42 am' />
      </div>
    </div>
  );
}
