import { Button, ThemeToggle } from 'personal-management-frontend';
import { Bell, Plus } from 'lucide-react';

export function Default() {
  return (
    <div className='flex items-center gap-3'>
      <ThemeToggle />
      <p className='text-muted-foreground text-sm'>
        Ghost icon button; opens a light / dark / system menu.
      </p>
    </div>
  );
}

export function InHeaderBar() {
  return (
    <div className='flex max-w-md items-center justify-between gap-4 border-b p-3'>
      <p className='text-sm font-medium'>Journal</p>
      <div className='flex items-center gap-2'>
        <Button size='sm'>
          <Plus />
          New entry
        </Button>
        <Button variant='ghost' size='sm' className='h-8 w-8 p-2'>
          <Bell aria-hidden='true' />
          <span className='sr-only'>Notifications</span>
        </Button>
        <ThemeToggle />
      </div>
    </div>
  );
}
