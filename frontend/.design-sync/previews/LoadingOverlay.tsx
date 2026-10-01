import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  LoadingOverlay,
} from 'lifecontour-frontend';

function EntryCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Morning run</CardTitle>
        <CardDescription>Tuesday, 14 July 2026 · 6:15 am</CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-sm'>
          8.2 km along the Yarra before work. Cold start, but the last two
          kilometres felt easy.
        </p>
        <div className='flex gap-2'>
          <Badge variant='secondary'>running</Badge>
          <Badge variant='secondary'>health</Badge>
        </div>
      </CardContent>
    </Card>
  );
}

export function Loading() {
  return (
    <LoadingOverlay isLoading text='Saving entry…' className='max-w-sm'>
      <EntryCard />
    </LoadingOverlay>
  );
}

export function Idle() {
  return (
    <LoadingOverlay isLoading={false} className='max-w-sm'>
      <EntryCard />
    </LoadingOverlay>
  );
}

export function OverList() {
  const contacts = [
    'Priya Raman',
    'Tom Whitfield',
    'Sarah Nguyen',
    'Dan Okafor',
  ];
  return (
    <LoadingOverlay isLoading text='Merging duplicates…' className='max-w-md'>
      <div className='space-y-2 rounded-md border p-4'>
        {contacts.map(name => (
          <div key={name} className='flex items-center justify-between py-1'>
            <span className='text-sm'>{name}</span>
            <span className='text-muted-foreground text-xs'>
              Last contacted 13 July 2026
            </span>
          </div>
        ))}
      </div>
    </LoadingOverlay>
  );
}
