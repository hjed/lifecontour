/**
 * Journal detail page - placeholder for future iteration
 *
 * This page will show a single journal entry when the journal system
 * is implemented in a future iteration.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BookOpen } from 'lucide-react';

export default function JournalDetailPage() {
  return (
    <AuthGuard>
      <div className='mb-6'>
        <h1 className='text-3xl font-bold tracking-tight'>Journal Entry</h1>
        <p className='text-muted-foreground'>
          Journal entry details will appear here.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <BookOpen className='h-5 w-5 text-green-500' />
            Coming Soon
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className='text-muted-foreground'>
            The journal system will be implemented in a future iteration.
          </p>
        </CardContent>
      </Card>
    </AuthGuard>
  );
}
