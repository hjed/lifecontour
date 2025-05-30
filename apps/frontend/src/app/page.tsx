export default function HomePage() {
  return (
    <main className='min-h-screen bg-background'>
      <div className='container mx-auto px-4 py-8'>
        <div className='max-w-4xl mx-auto text-center'>
          <h1 className='text-4xl font-bold text-foreground mb-6'>Personal Management System</h1>
          <p className='text-xl text-muted-foreground mb-8'>
            Your personal CRM & journal system with MCP protocol support
          </p>

          <div className='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-12'>
            <div className='p-6 border border-border rounded-lg bg-card'>
              <h2 className='text-xl font-semibold mb-3'>Contacts</h2>
              <p className='text-muted-foreground'>
                Manage your personal and professional contacts with tags and Google sync.
              </p>
            </div>

            <div className='p-6 border border-border rounded-lg bg-card'>
              <h2 className='text-xl font-semibold mb-3'>Journal</h2>
              <p className='text-muted-foreground'>
                Keep track of your thoughts, experiences, and mood with photo integration.
              </p>
            </div>

            <div className='p-6 border border-border rounded-lg bg-card'>
              <h2 className='text-xl font-semibold mb-3'>Calendar</h2>
              <p className='text-muted-foreground'>
                Sync with Google Calendar and link events to photos and journal entries.
              </p>
            </div>
          </div>

          <div className='mt-12 p-6 border border-border rounded-lg bg-muted/50'>
            <h3 className='text-lg font-semibold mb-3'>🚧 Under Development</h3>
            <p className='text-muted-foreground'>
              This is ITER1-001: Project Foundation. Features will be added incrementally following
              our agile approach.
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
