'use client';

import { useState } from 'react';
import { Sparkles, RefreshCw, Loader2, Bot, AlertTriangle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useDailySummary, useRegenerateDailySummary } from '@/lib/api/journals';
import { DailySummaryStatus } from '@/types/journals';

export interface DailySummaryViewProps {
  /** The date for which to fetch or display the summary (YYYY-MM-DD) */
  readonly date: string;
}

export function DailySummaryView({ date }: DailySummaryViewProps) {
  const [isRequested, setIsRequested] = useState(false);

  const { data, isLoading, isError, error, refetch } = useDailySummary(date, {
    enabled: isRequested,
  });

  const { mutate: regenerateSummary, isPending: isRegenerating } =
    useRegenerateDailySummary();

  const handleGenerateClick = () => {
    setIsRequested(true);
  };

  const handleRefreshClick = () => {
    regenerateSummary(date);
  };

  const handleRetryClick = () => {
    refetch();
  };

  // State 1: Not requested yet
  if (!isRequested) {
    return (
      <div className='mb-4'>
        <Button
          variant='outline'
          size='sm'
          onClick={handleGenerateClick}
          className='text-muted-foreground hover:text-primary gap-2'
          data-testid={`generate-summary-btn-${date}`}
        >
          <Bot className='h-4 w-4' />
          Generate AI Summary
        </Button>
      </div>
    );
  }

  // State 2: Loading (first time or from cache)
  if (isLoading) {
    return (
      <Card
        className='bg-muted/30 mb-4'
        data-testid={`summary-loading-${date}`}
      >
        <CardContent className='flex items-center gap-3 p-4'>
          <Loader2 className='text-muted-foreground h-5 w-5 animate-spin' />
          <p className='text-muted-foreground text-sm'>
            Generating daily summary...
          </p>
        </CardContent>
      </Card>
    );
  }

  // State 3: Network/fetch error
  if (isError) {
    return (
      <Card
        className='border-destructive/50 mb-4'
        data-testid={`summary-error-${date}`}
      >
        <CardContent className='flex flex-col gap-2 p-4'>
          <div className='text-destructive flex items-center gap-2'>
            <AlertTriangle className='h-4 w-4' />
            <span className='text-sm font-medium'>Failed to load summary</span>
          </div>
          <p className='text-muted-foreground text-sm'>
            {error instanceof Error
              ? error.message
              : 'An unexpected error occurred'}
          </p>
          <Button
            variant='outline'
            size='sm'
            onClick={handleRetryClick}
            className='mt-2 w-fit gap-2'
          >
            <RefreshCw className='h-4 w-4' />
            Try Again
          </Button>
        </CardContent>
      </Card>
    );
  }

  const attrs = data?.data?.attributes;

  // State 4: Disabled (Not enough data, should rarely happen if we check journals.length beforehand, but just in case)
  if (attrs?.status === DailySummaryStatus.DISABLED) {
    return null;
  }

  // State 5: AI generation failed — show explicit failure with regenerate action
  if (attrs?.status === DailySummaryStatus.FAILED) {
    return (
      <Card
        className='border-destructive/20 bg-destructive/5 mb-4'
        data-testid={`summary-failed-${date}`}
      >
        <CardContent className='flex flex-col gap-2 p-4'>
          <div className='text-destructive flex items-center gap-2'>
            <AlertTriangle className='h-4 w-4' />
            <span className='text-sm font-medium'>
              Summary generation failed
            </span>
          </div>
          <p className='text-muted-foreground text-sm'>
            The AI was unable to generate a summary for this day.
          </p>
          <Button
            variant='outline'
            size='sm'
            onClick={handleRefreshClick}
            disabled={isRegenerating}
            className='mt-2 w-fit gap-2'
            data-testid={`retry-summary-btn-${date}`}
          >
            <RefreshCw
              className={`h-4 w-4 ${isRegenerating ? 'animate-spin' : ''}`}
            />
            Retry Generation
          </Button>
        </CardContent>
      </Card>
    );
  }

  // State 6: Generated (or Generating fallback if returned as generating)
  const isGenerating =
    attrs?.status === DailySummaryStatus.GENERATING ||
    attrs?.status === DailySummaryStatus.PENDING ||
    isRegenerating;

  return (
    <Card
      className='bg-primary/5 border-primary/10 mb-4'
      data-testid={`summary-card-${date}`}
    >
      <CardContent className='flex flex-col gap-3 p-4'>
        <div className='flex items-center justify-between'>
          <div className='text-primary flex items-center gap-2'>
            <Sparkles className='h-4 w-4' />
            <span className='text-sm font-semibold'>AI Daily Summary</span>
            {isGenerating && (
              <Badge variant='secondary' className='ml-2 text-xs'>
                Generating...
              </Badge>
            )}
          </div>
          <Button
            variant='ghost'
            size='icon'
            className='text-muted-foreground hover:text-primary h-7 w-7'
            onClick={handleRefreshClick}
            disabled={isGenerating}
            aria-label='Refresh summary'
            data-testid={`refresh-summary-btn-${date}`}
          >
            <RefreshCw
              className={`h-3 w-3 ${isGenerating ? 'animate-spin' : ''}`}
            />
          </Button>
        </div>

        <p
          className='text-sm leading-relaxed'
          data-testid={`summary-text-${date}`}
        >
          {isGenerating
            ? 'Summary is being generated...'
            : attrs?.summary_text || 'No summary available.'}
        </p>

        {/* Lightweight Stats */}
        {attrs && (
          <div className='border-primary/10 mt-1 flex flex-wrap gap-3 border-t pt-3'>
            <div className='flex flex-col'>
              <span className='text-muted-foreground text-xs tracking-wider uppercase'>
                Journals
              </span>
              <span className='text-sm font-medium'>{attrs.journal_count}</span>
            </div>
            {attrs.event_count > 0 && (
              <div className='flex flex-col'>
                <span className='text-muted-foreground text-xs tracking-wider uppercase'>
                  Events
                </span>
                <span className='text-sm font-medium'>{attrs.event_count}</span>
              </div>
            )}
            {attrs.contact_count > 0 && (
              <div className='flex flex-col'>
                <span className='text-muted-foreground text-xs tracking-wider uppercase'>
                  Contacts
                </span>
                <span className='text-sm font-medium'>
                  {attrs.contact_count}
                </span>
              </div>
            )}
            {attrs.mood_average !== null &&
              attrs.mood_average !== undefined && (
                <div className='flex flex-col'>
                  <span className='text-muted-foreground text-xs tracking-wider uppercase'>
                    Avg Mood
                  </span>
                  <span className='text-sm font-medium'>
                    {attrs.mood_average.toFixed(1)}/10
                  </span>
                </div>
              )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
