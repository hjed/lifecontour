import Link from 'next/link';
import { ChevronRight, Home } from 'lucide-react';

interface TaskListBreadcrumbProps {
  readonly name: string;
}

function Separator() {
  return <ChevronRight aria-hidden='true' className='size-4 shrink-0' />;
}

/**
 * Home › Tasks › the list. "Tasks" is text until the Tasks overview exists to
 * link to.
 */
export function TaskListBreadcrumb({ name }: TaskListBreadcrumbProps) {
  return (
    <nav aria-label='Breadcrumb' className='text-muted-foreground text-sm'>
      <ol className='flex flex-wrap items-center gap-x-1'>
        <li className='flex items-center'>
          <Link
            href='/'
            className='hover:text-foreground inline-flex items-center justify-center transition-colors max-sm:min-h-11 max-sm:min-w-11'
          >
            <Home aria-hidden='true' className='size-4' />
            <span className='sr-only'>Home</span>
          </Link>
        </li>
        <li className='flex items-center gap-1'>
          <Separator />
          <span>Tasks</span>
        </li>
        <li className='flex min-w-0 items-center gap-1'>
          <Separator />
          <span
            aria-current='page'
            className='text-foreground min-w-0 font-medium wrap-anywhere'
          >
            {name}
          </span>
        </li>
      </ol>
    </nav>
  );
}
