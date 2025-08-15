import { AuthGuard } from '@/components/auth/AuthGuard';

export default function SearchPage() {
  return (
    <AuthGuard>
      <div className='space-y-4'>
        <h1 className='text-2xl font-bold tracking-tight'>Search</h1>
        <p className='text-muted-foreground'>Global search coming soon.</p>
      </div>
    </AuthGuard>
  );
}
