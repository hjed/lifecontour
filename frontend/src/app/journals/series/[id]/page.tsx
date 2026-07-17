/**
 * Journal series detail page
 *
 * Displays a series (a named group of related journals) with its member
 * journals, allowing navigation to members and membership removal.
 */

'use client';

import Link from 'next/link';
import { useRouter, useParams } from 'next/navigation';
import { ArrowLeft, Layers, Trash2, X } from 'lucide-react';
import { format, parseISO } from 'date-fns';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useDeleteJournalSeries,
  useJournalSeriesDetail,
  useRemoveJournalFromSeries,
} from '@/lib/api/journals';

export default function JournalSeriesDetailPage() {
  const router = useRouter();
  const params = useParams();
  const seriesId = params.id as string;

  const { data: series, isLoading, error } = useJournalSeriesDetail(seriesId);
  const removeFromSeries = useRemoveJournalFromSeries();
  const deleteSeries = useDeleteJournalSeries();

  const handleRemoveMember = async (journalId: number) => {
    await removeFromSeries.mutateAsync({
      journalId: String(journalId),
      seriesId,
    });
  };

  const handleDeleteSeries = async () => {
    if (
      !confirm(
        'Delete this series? The journals in it are kept — only the grouping is removed.'
      )
    ) {
      return;
    }
    await deleteSeries.mutateAsync(seriesId);
    router.push('/journals');
  };

  return (
    <AuthGuard>
      <div className='container mx-auto max-w-4xl py-6'>
        <div className='mb-6'>
          <Button
            variant='ghost'
            size='sm'
            onClick={() => router.back()}
            className='gap-2'
          >
            <ArrowLeft className='h-4 w-4' />
            Back
          </Button>
        </div>

        {isLoading && (
          <div className='space-y-4' data-testid='series-loading'>
            <Skeleton className='h-8 w-1/2' />
            <Skeleton className='h-32 w-full' />
          </div>
        )}

        {error && (
          <Alert variant='destructive'>
            Failed to load series: {error.message}
          </Alert>
        )}

        {series && (
          <Card data-testid='series-detail'>
            <CardHeader className='flex flex-row items-start justify-between'>
              <div className='space-y-2'>
                <CardTitle className='flex items-center gap-2'>
                  <Layers className='h-5 w-5' />
                  <span data-testid='series-name'>{series.name}</span>
                  {series.auto_created && (
                    <Badge variant='secondary' className='text-xs'>
                      From calendar
                    </Badge>
                  )}
                </CardTitle>
                {series.description && (
                  <p className='text-muted-foreground text-sm'>
                    {series.description}
                  </p>
                )}
              </div>
              <Button
                variant='ghost'
                size='sm'
                onClick={handleDeleteSeries}
                className='text-destructive gap-2'
                data-testid='delete-series-button'
              >
                <Trash2 className='h-4 w-4' />
                Delete Series
              </Button>
            </CardHeader>
            <CardContent>
              <div className='mb-2 text-sm font-medium'>
                Journals in this series
              </div>
              {series.member_journals.length === 0 ? (
                <p className='text-muted-foreground text-sm'>
                  No journals in this series yet.
                </p>
              ) : (
                <ul
                  className='divide-border divide-y'
                  data-testid='series-members'
                >
                  {series.member_journals.map(member => (
                    <li
                      key={member.id}
                      className='flex items-center justify-between py-2'
                      data-testid={`series-member-${member.id}`}
                    >
                      <Link
                        href={`/journals/${member.id}`}
                        className='hover:underline'
                      >
                        <span>{member.title}</span>
                        {member.event_date_range_start && (
                          <span className='text-muted-foreground ml-2 text-xs'>
                            {format(
                              parseISO(member.event_date_range_start),
                              'd MMM yyyy'
                            )}
                          </span>
                        )}
                      </Link>
                      <Button
                        variant='ghost'
                        size='sm'
                        onClick={() => handleRemoveMember(member.id)}
                        aria-label={`Remove ${member.title} from series`}
                        data-testid={`remove-member-${member.id}`}
                      >
                        <X className='h-4 w-4' />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </AuthGuard>
  );
}
