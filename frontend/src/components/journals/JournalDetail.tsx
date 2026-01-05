/**
 * JournalDetail component for displaying full journal information with inline editing.
 *
 * Main detail view with sections for identity, content, types, relationships, and hierarchy.
 * Follows responsive design patterns with mobile-first approach.
 */

'use client';

import { ArrowLeft, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { JournalIdentityInline } from './JournalIdentityInline';
import { JournalContentInline } from './JournalContentInline';
import { useUpdateJournalField } from '@/lib/api/journals';
import type { JournalResource } from '@/types/journals';
import { cn } from '@/lib/utils';

interface JournalDetailProps {
  readonly journal: JournalResource;
  readonly isLoading?: boolean;
  readonly error?: Error | null;
  readonly className?: string;
}

/**
 * JournalDetail component displays full journal information with inline editing capabilities.
 */
export function JournalDetail({
  journal,
  isLoading = false,
  error = null,
  className,
}: JournalDetailProps) {
  const router = useRouter();
  const updateFieldMutation = useUpdateJournalField();

  // Handle content update
  const handleContentSave = async (value: string) => {
    await updateFieldMutation.mutateAsync({
      journalId: journal.id,
      fieldName: 'content',
      value,
    });
  };

  // Handle back navigation
  const handleBack = () => {
    router.push('/journals');
  };

  // Loading state
  if (isLoading) {
    return (
      <div className={cn('space-y-6', className)}>
        <Skeleton className='h-10 w-full' />
        <Skeleton className='h-32 w-full' />
        <Skeleton className='h-64 w-full' />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <Alert variant='destructive' className={className}>
        <p>Failed to load journal: {error.message}</p>
      </Alert>
    );
  }

  const { attributes } = journal;
  const calendarColor = attributes.calendar?.color || '#6b7280';

  return (
    <div className={cn('space-y-6', className)} data-testid='journal-detail'>
      {/* Header with back button */}
      <div className='flex items-center justify-between'>
        <Button
          variant='ghost'
          size='sm'
          onClick={handleBack}
          aria-label='Back to journals'
          data-testid='back-button'
        >
          <ArrowLeft className='mr-2 h-4 w-4' />
          Back
        </Button>
        <Button
          variant='ghost'
          size='sm'
          aria-label='Delete journal'
          data-testid='delete-button'
        >
          <Trash2 className='text-destructive h-4 w-4' />
        </Button>
      </div>

      {/* Main content card */}
      <Card className='relative overflow-hidden'>
        {/* Calendar color bar */}
        <div
          className='absolute top-0 left-0 h-full w-1'
          style={{ backgroundColor: calendarColor }}
          aria-hidden='true'
        />

        <CardHeader className='pl-5'>
          {/* Identity section - title and date range */}
          <JournalIdentityInline journal={journal} />
        </CardHeader>

        <CardContent className='space-y-6 pl-5'>
          {/* Metadata bar - types, calendar, tags */}
          <div className='flex flex-wrap items-center gap-2'>
            {/* Type badges */}
            {attributes.types.map(type => (
              <Badge
                key={type}
                variant='secondary'
                data-testid={`type-badge-${type}`}
              >
                {type}
              </Badge>
            ))}

            {/* Calendar badge */}
            {attributes.calendar && (
              <Badge
                variant='outline'
                style={{
                  borderColor: attributes.calendar.color || undefined,
                  color: attributes.calendar.color || undefined,
                }}
                data-testid='calendar-badge'
              >
                {attributes.calendar.name}
              </Badge>
            )}

            {/* Tag badges */}
            {attributes.tags?.map(tag => (
              <Badge
                key={tag.id}
                variant='outline'
                style={{
                  borderColor: tag.color || undefined,
                  color: tag.color || undefined,
                }}
                data-testid={`tag-badge-${tag.id}`}
              >
                {tag.name}
              </Badge>
            ))}
          </div>

          <Separator />

          {/* Content section */}
          <div>
            <h3 className='mb-2 text-sm font-semibold'>Content</h3>
            <JournalContentInline
              value={attributes.content}
              onSave={handleContentSave}
              placeholder='Add journal content...'
              data-testid='journal-content'
            />
          </div>

          {/* Footer - timestamps */}
          <Separator />
          <div className='text-muted-foreground flex flex-wrap gap-4 text-xs'>
            {attributes.created_at && (
              <span>
                Created:{' '}
                {format(new Date(attributes.created_at), 'PPp', {
                  locale: enAU,
                })}
              </span>
            )}
            {attributes.updated_at && (
              <span>
                Updated:{' '}
                {format(new Date(attributes.updated_at), 'PPp', {
                  locale: enAU,
                })}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
