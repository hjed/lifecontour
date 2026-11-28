import Link from 'next/link';
import { Button } from '@/components/ui/button';

/** A missing list, another user's, or an id that cannot be one: all alike. */
export function TaskListNotFound() {
  return (
    <div className='mx-auto max-w-md space-y-3 py-12 text-center'>
      <h1 className='text-2xl font-semibold'>List not found</h1>
      <p className='text-muted-foreground'>
        This list doesn&apos;t exist, or it has been deleted.
      </p>
      <Button asChild variant='outline' className='max-sm:min-h-11'>
        <Link href='/'>Go home</Link>
      </Button>
    </div>
  );
}
