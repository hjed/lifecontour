import { Button } from 'personal-management-frontend';
import { Plus, Trash2, Download } from 'lucide-react';

export function Variants() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button>Save entry</Button>
      <Button variant='secondary'>Add tag</Button>
      <Button variant='outline'>Cancel</Button>
      <Button variant='ghost'>Skip</Button>
      <Button variant='destructive'>Delete journal</Button>
      <Button variant='link'>View history</Button>
    </div>
  );
}

export function Sizes() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button size='sm'>Small</Button>
      <Button size='default'>Default</Button>
      <Button size='lg'>Large</Button>
      <Button size='icon' aria-label='Add journal entry'>
        <Plus />
      </Button>
    </div>
  );
}

export function WithIcons() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button>
        <Plus />
        New entry
      </Button>
      <Button variant='outline'>
        <Download />
        Export PDF
      </Button>
      <Button variant='destructive'>
        <Trash2 />
        Remove contact
      </Button>
    </div>
  );
}

export function Disabled() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button disabled>Save entry</Button>
      <Button variant='secondary' disabled>
        Add tag
      </Button>
      <Button variant='outline' disabled>
        Cancel
      </Button>
      <Button variant='destructive' disabled>
        Delete journal
      </Button>
    </div>
  );
}
