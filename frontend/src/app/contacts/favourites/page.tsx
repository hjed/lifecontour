/**
 * Favourites contacts page - placeholder for ITER1.5-004
 *
 * This page will show only favourited contacts when the favourites
 * functionality is implemented in ITER1.5-004.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Star } from 'lucide-react';

export default function FavouritesPage() {
  return (
    <AuthGuard>
      <div className='container mx-auto px-4 py-8'>
        <div className='mb-6'>
          <h1 className='text-3xl font-bold tracking-tight'>
            Favourite Contacts
          </h1>
          <p className='text-muted-foreground'>
            Your starred contacts will appear here.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className='flex items-center gap-2'>
              <Star className='h-5 w-5 text-yellow-500' />
              Coming Soon
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className='text-muted-foreground'>
              The favourites functionality will be implemented in ITER1.5-004.
              You&apos;ll be able to star your important contacts and view them
              here.
            </p>
          </CardContent>
        </Card>
      </div>
    </AuthGuard>
  );
}
