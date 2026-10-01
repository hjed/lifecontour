import { Checkbox, Label } from 'lifecontour-frontend';

export function States() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <Checkbox id='cb-unchecked' />
        <Label htmlFor='cb-unchecked'>Unchecked</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='cb-checked' defaultChecked />
        <Label htmlFor='cb-checked'>Checked</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='cb-disabled' disabled />
        <Label htmlFor='cb-disabled'>Disabled</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='cb-disabled-checked' disabled defaultChecked />
        <Label htmlFor='cb-disabled-checked'>Disabled and checked</Label>
      </div>
    </div>
  );
}

export function FilterList() {
  return (
    <div className='flex max-w-sm flex-col gap-3'>
      <p className='text-sm font-medium'>Filter entries by type</p>
      <div className='flex items-center gap-2'>
        <Checkbox id='type-note' defaultChecked />
        <Label htmlFor='type-note'>Note</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='type-event' defaultChecked />
        <Label htmlFor='type-event'>Event</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='type-activity' />
        <Label htmlFor='type-activity'>Outdoor activity</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='type-mood' />
        <Label htmlFor='type-mood'>Mood rating</Label>
      </div>
    </div>
  );
}

export function WithDescription() {
  return (
    <div className='flex max-w-sm items-start gap-2'>
      <Checkbox id='link-contacts' defaultChecked className='mt-1' />
      <div className='flex flex-col gap-2'>
        <Label htmlFor='link-contacts'>Link mentioned contacts</Label>
        <p className='text-muted-foreground text-sm'>
          When saving, people named in the entry are matched to your contacts
          and linked automatically.
        </p>
      </div>
    </div>
  );
}

export function Invalid() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <div className='flex items-center gap-2'>
        <Checkbox
          id='confirm-merge'
          aria-invalid='true'
          aria-describedby='confirm-merge-error'
        />
        <Label htmlFor='confirm-merge' className='text-destructive'>
          I understand the two contacts will be merged
        </Label>
      </div>
      <p id='confirm-merge-error' className='text-destructive text-sm'>
        You must confirm before merging.
      </p>
    </div>
  );
}
