import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from 'lifecontour-frontend';

export function Basic() {
  return (
    <Card className='max-w-sm'>
      <CardHeader>
        <CardTitle>Morning run</CardTitle>
        <CardDescription>Tuesday, 14 July 2026 · 6:15 am</CardDescription>
      </CardHeader>
      <CardContent>
        <p className='text-sm'>
          8.2 km along the Yarra before work. Cold start, but the last two
          kilometres felt easy — quickest split of the month.
        </p>
      </CardContent>
    </Card>
  );
}

export function WithFooter() {
  return (
    <Card className='max-w-sm'>
      <CardHeader>
        <CardTitle>Coffee with Priya</CardTitle>
        <CardDescription>Logged 3 days ago</CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-sm'>
          Caught up at Patricia. She&apos;s moving to the Melbourne office in
          September and asked about climbing gyms nearby.
        </p>
        <div className='flex gap-2'>
          <Badge variant='secondary'>catch-up</Badge>
          <Badge variant='secondary'>work</Badge>
        </div>
      </CardContent>
      <CardFooter className='gap-2'>
        <Button size='sm'>Open entry</Button>
        <Button size='sm' variant='outline'>
          Add follow-up
        </Button>
      </CardFooter>
    </Card>
  );
}

export function StatCards() {
  const stats = [
    { label: 'Entries this month', value: '24', delta: '+6 vs June' },
    { label: 'Contacts logged', value: '11', delta: '3 new' },
    { label: 'Distance run', value: '92 km', delta: '+14 km' },
  ];
  return (
    <div className='grid gap-4 sm:grid-cols-3'>
      {stats.map(s => (
        <Card key={s.label}>
          <CardHeader className='pb-2'>
            <CardDescription>{s.label}</CardDescription>
            <CardTitle className='text-3xl'>{s.value}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className='text-muted-foreground text-xs'>{s.delta}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
