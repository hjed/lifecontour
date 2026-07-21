import { CardSkeleton } from 'personal-management-frontend';

export function Single() {
  return <CardSkeleton className='max-w-sm' />;
}

export function ContactGrid() {
  return (
    <div className='grid gap-4 sm:grid-cols-3'>
      <CardSkeleton />
      <CardSkeleton />
      <CardSkeleton />
    </div>
  );
}

export function LoadingJournalFeed() {
  return (
    <div className='max-w-md space-y-4'>
      <p className='text-muted-foreground text-sm'>
        Loading entries for July 2026…
      </p>
      <CardSkeleton />
      <CardSkeleton />
      <CardSkeleton />
    </div>
  );
}
