import {
  Card,
  CardContent,
  CardHeader,
  Skeleton,
} from 'personal-management-frontend';

export function Shapes() {
  return (
    <div className='flex items-center gap-4'>
      <Skeleton className='h-12 w-12 rounded-full' />
      <div className='space-y-2'>
        <Skeleton className='h-4 w-56' />
        <Skeleton className='h-4 w-32' />
      </div>
    </div>
  );
}

export function ContactCard() {
  return (
    <Card className='max-w-sm'>
      <CardHeader className='space-y-2'>
        <Skeleton className='h-5 w-48' />
        <Skeleton className='h-4 w-32' />
      </CardHeader>
      <CardContent className='space-y-2'>
        <Skeleton className='h-4 w-full' />
        <Skeleton className='h-4 w-full' />
        <Skeleton className='h-4 w-2/3' />
        <div className='flex gap-2 pt-2'>
          <Skeleton className='h-5 w-16 rounded-full' />
          <Skeleton className='h-5 w-20 rounded-full' />
        </div>
      </CardContent>
    </Card>
  );
}

export function JournalList() {
  return (
    <div className='max-w-md space-y-4'>
      {[0, 1, 2, 3].map(row => (
        <div key={row} className='flex items-center gap-3'>
          <Skeleton className='h-10 w-10 rounded-full' />
          <div className='flex-1 space-y-2'>
            <Skeleton className='h-4 w-3/4' />
            <Skeleton className='h-3 w-1/2' />
          </div>
          <Skeleton className='h-4 w-20' />
        </div>
      ))}
    </div>
  );
}
