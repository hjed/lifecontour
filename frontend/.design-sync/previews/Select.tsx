import {
  Label,
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from 'lifecontour-frontend';

export function OpenWithGroups() {
  return (
    <div className='flex flex-col gap-2'>
      <Label htmlFor='entry-type-select'>Entry type</Label>
      <Select open modal={false} defaultValue='event'>
        <SelectTrigger id='entry-type-select' className='w-64'>
          <SelectValue placeholder='Choose a type' />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Journal</SelectLabel>
            <SelectItem value='note'>Note</SelectItem>
            <SelectItem value='event'>Event</SelectItem>
            <SelectItem value='mood'>Mood rating</SelectItem>
          </SelectGroup>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Outdoors</SelectLabel>
            <SelectItem value='run'>Run</SelectItem>
            <SelectItem value='ride'>Ride</SelectItem>
            <SelectItem value='hike' disabled>
              Hike (needs Strava)
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}

export function TriggerStates() {
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='select-placeholder'>Calendar (empty)</Label>
        <Select>
          <SelectTrigger id='select-placeholder' className='w-64'>
            <SelectValue placeholder='Select a calendar' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='personal'>Personal</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='select-small'>Sort by (small)</Label>
        <Select defaultValue='recent'>
          <SelectTrigger id='select-small' size='sm' className='w-64'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='recent'>Most recent</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='select-invalid' className='text-destructive'>
          Tag
        </Label>
        <Select>
          <SelectTrigger id='select-invalid' aria-invalid className='w-64'>
            <SelectValue placeholder='Select a tag' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='running'>running</SelectItem>
          </SelectContent>
        </Select>
        <p className='text-destructive text-sm'>Choose at least one tag.</p>
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='select-disabled'>Linked contact</Label>
        <Select defaultValue='priya' disabled>
          <SelectTrigger id='select-disabled' className='w-64'>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='priya'>Priya Raman</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
