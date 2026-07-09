/**
 * IncompleteOutdoorActivitiesList — the incomplete outdoor activities review.
 *
 * Lists the user's outdoor activity journals that are likely missing
 * important detail, with the matched reason(s) shown as badges, a link to the
 * journal to fix it, and a reversible whole-entry dismiss. A "Show dismissed"
 * switch reveals dismissed entries so they can be un-dismissed.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { AlertCircle } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Alert } from '@/components/ui/alert';
import { JournalTypeBadges } from '@/components/journals/JournalTypeBadges';
import {
  IncompletenessReason,
  useDismissIncompleteOutdoorActivity,
  useIncompleteOutdoorActivities,
  useUndismissIncompleteOutdoorActivity,
} from '@/lib/api/incomplete-outdoor-activities';
import { formatDateRange } from '@/lib/date-utils';
import { cn } from '@/lib/utils';

// Human labels for the backend IncompletenessReason enum values
const REASON_LABELS: Record<IncompletenessReason, string> = {
  no_attributes: 'No attributes set',
  missing_template: 'Missing template',
  no_participants: 'No participants',
};

export function IncompleteOutdoorActivitiesList() {
  const [showDismissed, setShowDismissed] = useState(false);
  const { data, isLoading, error } =
    useIncompleteOutdoorActivities(showDismissed);
  const dismissMutation = useDismissIncompleteOutdoorActivity();
  const undismissMutation = useUndismissIncompleteOutdoorActivity();

  const entries = data?.data ?? [];

  return (
    <Card>
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-4'>
          <div className='space-y-1.5'>
            <CardTitle>Incomplete activities</CardTitle>
            <CardDescription>
              Outdoor activities that may be missing important detail. Fill in
              the gaps while memory is fresh, or dismiss entries that are
              genuinely fine.
            </CardDescription>
          </div>
          <div className='flex items-center gap-2'>
            <Switch
              id='show-dismissed'
              checked={showDismissed}
              onCheckedChange={setShowDismissed}
              data-testid='show-dismissed-switch'
            />
            <Label htmlFor='show-dismissed'>Show dismissed</Label>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className='space-y-3' data-testid='incomplete-list-loading'>
            <Skeleton className='h-20 w-full' />
            <Skeleton className='h-20 w-full' />
          </div>
        )}

        {error && !isLoading && (
          <Alert variant='destructive' data-testid='incomplete-list-error'>
            <p>Failed to load incomplete activities: {error.message}</p>
          </Alert>
        )}

        {!isLoading && !error && (
          <div data-testid='incomplete-list-ready'>
            {entries.length === 0 ? (
              <p
                className='text-muted-foreground py-4 text-sm'
                data-testid='incomplete-empty-state'
              >
                No incomplete activities — you&apos;re all caught up.
              </p>
            ) : (
              <ul
                className='space-y-3'
                aria-label='Incomplete outdoor activities'
              >
                {entries.map(entry => {
                  const { id, attributes } = entry;
                  const dismissed = attributes.dismissed;
                  return (
                    <li
                      key={id}
                      className={cn(
                        'space-y-2 rounded-lg border p-4',
                        dismissed && 'opacity-60'
                      )}
                      data-testid={`incomplete-activity-item-${id}`}
                      data-dismissed={dismissed}
                    >
                      <div className='flex flex-wrap items-start justify-between gap-2'>
                        <div className='space-y-1'>
                          <Link
                            href={`/journals/${id}` as Route}
                            className='font-medium underline-offset-4 hover:underline'
                          >
                            {attributes.title}
                          </Link>
                          <p className='text-muted-foreground text-sm'>
                            {formatDateRange(
                              attributes.event_date_range.start,
                              attributes.event_date_range.end
                            )}
                          </p>
                        </div>
                        {dismissed ? (
                          <Button
                            variant='outline'
                            size='sm'
                            onClick={() => undismissMutation.mutate(id)}
                            disabled={
                              undismissMutation.isPending &&
                              undismissMutation.variables === id
                            }
                            aria-label={`Restore "${attributes.title}" to the incomplete review`}
                            data-testid={`incomplete-undismiss-btn-${id}`}
                          >
                            Un-dismiss
                          </Button>
                        ) : (
                          <Button
                            variant='outline'
                            size='sm'
                            onClick={() => dismissMutation.mutate(id)}
                            disabled={
                              dismissMutation.isPending &&
                              dismissMutation.variables === id
                            }
                            aria-label={`Dismiss "${attributes.title}" from the incomplete review`}
                            data-testid={`incomplete-dismiss-btn-${id}`}
                          >
                            Dismiss
                          </Button>
                        )}
                      </div>
                      <JournalTypeBadges
                        types={attributes.subtypes}
                        data-testid={`incomplete-type-badges-${id}`}
                      />
                      <ul
                        className='flex flex-wrap gap-2'
                        aria-label='Reasons flagged'
                      >
                        {attributes.reasons.map(reason => (
                          <li key={reason}>
                            <Badge
                              variant='secondary'
                              className='flex items-center gap-1.5'
                              data-testid={`reason-badge-${reason}`}
                            >
                              <AlertCircle
                                className='h-3.5 w-3.5'
                                aria-hidden='true'
                              />
                              <span>{REASON_LABELS[reason]}</span>
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
