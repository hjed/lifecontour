/**
 * Contact groups page - placeholder for ITER1.5-004
 *
 * This page will show contacts in a specific group when the groups
 * functionality is implemented in ITER1.5-004.
 */

'use client';

import { useParams } from 'next/navigation';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Users } from 'lucide-react';

export default function ContactGroupPage() {
  const params = useParams();
  const groupId = params.id as string;

  return (
    <AuthGuard>
      <div className='mb-6'>
        <h1 className='text-3xl font-bold tracking-tight'>
          Contact Group {groupId}
        </h1>
        <p className='text-muted-foreground'>
          Contacts in group {groupId} will appear here.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            <Users className='h-5 w-5 text-blue-500' />
            Coming Soon
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className='text-muted-foreground'>
            The contact groups functionality will be implemented in ITER1.5-004.
            You&apos;ll be able to organize your contacts into groups and view
            them here.
          </p>
        </CardContent>
      </Card>
    </AuthGuard>
  );
}
