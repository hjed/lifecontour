import { TableSkeleton } from 'personal-management-frontend';

export function Default() {
  return <TableSkeleton />;
}

export function CompactJournalTable() {
  return <TableSkeleton rows={3} columns={4} />;
}

export function WideContactsTable() {
  return <TableSkeleton rows={6} columns={7} />;
}

export function InPageHeader() {
  return (
    <div className='space-y-4'>
      <div className='flex items-center justify-between'>
        <h2 className='text-xl font-semibold'>Journal entries</h2>
        <span className='text-muted-foreground text-sm'>Loading…</span>
      </div>
      <div className='rounded-md border p-4'>
        <TableSkeleton rows={5} columns={4} />
      </div>
    </div>
  );
}
