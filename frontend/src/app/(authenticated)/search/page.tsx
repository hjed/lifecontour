'use client';

import { Suspense, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { Search, Users, Book, AlertCircle, Loader2 } from 'lucide-react';
import { useGlobalSearch } from '@/lib/api/search';
import {
  groupSearchResults,
  transformSearchResultToDisplayJournal,
} from '@/utils/searchUtils';
import { useDisplayContacts } from '@/hooks/useDisplayContacts';
import { ContactList } from '@/components/contacts/ContactList';
import { JournalList } from '@/components/journals/JournalList';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { Separator } from '@/components/ui/separator';

export default function SearchPage() {
  return (
    <AuthGuard>
      <Suspense
        fallback={
          <div className='flex items-center justify-center p-12'>
            <Loader2 className='text-muted-foreground h-8 w-8 animate-spin' />
          </div>
        }
      >
        <SearchResultsContent />
      </Suspense>
    </AuthGuard>
  );
}

function SearchResultsContent() {
  const searchParams = useSearchParams();
  const query = searchParams.get('q') || '';

  const { data, isLoading, error } = useGlobalSearch(
    { q: query, limit: 50 },
    { enabled: query.trim().length > 0 }
  );

  const { contacts, journals } = useMemo(() => {
    if (!data?.data) return { contacts: [], journals: [] };
    return groupSearchResults(data.data);
  }, [data]);

  const displayContacts = useDisplayContacts(contacts, true);
  const displayJournals = useMemo(
    () => journals.map(transformSearchResultToDisplayJournal),
    [journals]
  );

  const hasResults = contacts.length > 0 || journals.length > 0;

  if (!query.trim()) {
    return (
      <div className='space-y-4'>
        <h1 className='text-3xl font-bold tracking-tight'>Search</h1>
        <Card>
          <CardContent className='flex flex-col items-center justify-center py-12'>
            <Search className='text-muted-foreground mb-4 h-12 w-12' />
            <p className='text-muted-foreground text-lg'>
              Enter a search term in the header to find contacts and journals.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className='space-y-6'>
      <div>
        <h1 className='text-3xl font-bold tracking-tight'>Search Results</h1>
        <p className='text-muted-foreground'>
          Showing results for{' '}
          <span className='text-foreground font-semibold'>
            &quot;{query}&quot;
          </span>
          {data?.meta?.processing_time_ms !== undefined &&
            ` (${data.meta.processing_time_ms}ms)`}
        </p>
      </div>

      {error && (
        <Alert variant='destructive'>
          <AlertCircle className='h-4 w-4' />
          <AlertTitle>Search Failed</AlertTitle>
          <AlertDescription>
            {error instanceof Error
              ? error.message
              : 'An error occurred while searching. Please try again.'}
          </AlertDescription>
        </Alert>
      )}

      {isLoading && (
        <div className='space-y-8'>
          <div className='space-y-4'>
            <h2 className='flex items-center gap-2 text-xl font-semibold'>
              <Users className='text-muted-foreground h-5 w-5' />
              Contacts
            </h2>
            <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
              {Array.from({ length: 3 }).map((_, i) => (
                <Card key={i}>
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
          </div>
        </div>
      )}

      {!isLoading && !error && !hasResults && (
        <Card>
          <CardContent className='flex flex-col items-center justify-center py-16 text-center'>
            <Search className='text-muted-foreground mb-4 h-12 w-12 opacity-50' />
            <h3 className='mb-2 text-lg font-semibold'>No results found</h3>
            <p className='text-muted-foreground max-w-md'>
              We couldn&apos;t find any contacts or journals matching &quot;
              {query}&quot;. Try checking for typos or using different keywords.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && !error && hasResults && (
        <div className='space-y-10'>
          {displayContacts.length > 0 && (
            <section className='space-y-4'>
              <div className='flex items-center justify-between'>
                <h2 className='flex items-center gap-2 text-xl font-semibold'>
                  <Users className='text-primary h-5 w-5' />
                  Contacts ({displayContacts.length})
                </h2>
              </div>
              <ContactList contacts={displayContacts} />
            </section>
          )}

          {displayContacts.length > 0 && displayJournals.length > 0 && (
            <Separator />
          )}

          {displayJournals.length > 0 && (
            <section className='space-y-4'>
              <div className='flex items-center justify-between'>
                <h2 className='flex items-center gap-2 text-xl font-semibold'>
                  <Book className='text-primary h-5 w-5' />
                  Journals ({displayJournals.length})
                </h2>
              </div>
              <JournalList journals={displayJournals} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
