import { PageLoading } from 'lifecontour-frontend';

export function Default() {
  return (
    <div className='w-full rounded-md border'>
      <PageLoading />
    </div>
  );
}

export function CustomText() {
  return (
    <div className='w-full rounded-md border'>
      <PageLoading text='Loading your journal…' />
    </div>
  );
}

export function ContactsRoute() {
  return (
    <div className='w-full space-y-4'>
      <div className='flex items-center justify-between'>
        <h2 className='text-xl font-semibold'>Contacts</h2>
        <span className='text-muted-foreground text-sm'>Melbourne · AEST</span>
      </div>
      <div className='rounded-md border'>
        <PageLoading text='Fetching contacts…' />
      </div>
    </div>
  );
}
