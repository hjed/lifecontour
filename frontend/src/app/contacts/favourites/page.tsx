/**
 * Favourites contacts page showing only starred contacts.
 *
 * Displays a filtered list of contacts that have been marked as favourites,
 * with the same functionality as the main contacts page but filtered.
 */

'use client';

import { Star, Users } from 'lucide-react';
import Link from 'next/link';
import { useContacts } from '@/lib/api/contacts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { ContactList } from '@/components/contacts/ContactList';
import { useDisplayContacts } from '@/hooks/useDisplayContacts';

export default function FavouritesPage() {
  return (
    <AuthGuard>
      <FavouritesPageContent />
    </AuthGuard>
  );
}

function FavouritesPageContent() {
  // Fetch only favourite contacts
  const { data, isLoading, error } = useContacts({ favourite: true });

  // Transform contacts for display
  const displayContacts = useDisplayContacts(data?.data);

  if (error) {
    return (
      <div className='container mx-auto px-4 py-8'>
        <Alert variant='destructive'>
          <AlertDescription>
            {error instanceof Error
              ? error.message
              : 'Failed to load favourite contacts'}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className='space-y-6'>
      {/* Header */}
      <div className='mb-6'>
        <h1 className='text-3xl font-bold tracking-tight'>
          Favourite Contacts
        </h1>
        <p className='text-muted-foreground'>
          Your starred contacts will appear here.
        </p>
      </div>

      {/* Contact List */}
      {isLoading ? (
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} data-testid='skeleton'>
              <CardHeader>
                <Skeleton className='h-6 w-3/4' />
                <Skeleton className='h-4 w-1/2' />
              </CardHeader>
              <CardContent>
                <div className='space-y-2'>
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-4 w-2/3' />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <ContactList
          contacts={displayContacts}
          emptyState={
            <Card>
              <CardContent className='pt-6'>
                <div className='py-8 text-center' data-testid='empty-state'>
                  <Star className='text-muted-foreground mx-auto mb-4 h-12 w-12' />
                  <h3 className='mb-2 text-lg font-semibold'>
                    No favourite contacts found
                  </h3>
                  <p className='text-muted-foreground mb-4'>
                    Star some contacts to see them here
                  </p>
                  <Button asChild>
                    <Link href='/contacts'>
                      <Users className='mr-2 h-4 w-4' />
                      Browse All Contacts
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          }
        />
      )}
    </div>
  );
}
