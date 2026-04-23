/**
 * Contact AI Summary component.
 *
 * Displays the AI-generated interaction summary with status indicators,
 * follow-up suggestions, and user override controls.
 */

'use client';

import {
  Bot,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Ban,
  Sparkles,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ContactSummaryResource, ContactSummaryStatus } from '@/types/contacts';

export interface ContactSummaryProps {
  /** The summary resource from the API (null if no summary exists) */
  readonly summary: ContactSummaryResource | null | undefined;
  /** Contact ID for refresh action */
  readonly contactId: string;
  /** Whether the component is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
}

/**
 * Status configuration for rendering the status badge.
 */
const STATUS_CONFIG: Record<
  ContactSummaryStatus,
  {
    label: string;
    variant: 'default' | 'secondary' | 'destructive' | 'outline';
    icon: typeof Bot;
  }
> = {
  [ContactSummaryStatus.PENDING]: {
    label: 'Pending',
    variant: 'secondary',
    icon: Loader2,
  },
  [ContactSummaryStatus.GENERATING]: {
    label: 'Generating…',
    variant: 'secondary',
    icon: Loader2,
  },
  [ContactSummaryStatus.GENERATED]: {
    label: 'Generated',
    variant: 'default',
    icon: Sparkles,
  },
  [ContactSummaryStatus.FAILED]: {
    label: 'Failed',
    variant: 'destructive',
    icon: AlertTriangle,
  },
  [ContactSummaryStatus.DISABLED]: {
    label: 'Disabled',
    variant: 'outline',
    icon: Ban,
  },
};

/**
 * Contact Summary display component.
 *
 * Shows the AI-generated summary, status badge, follow-up suggestions,
 * and user override information.
 */
export function ContactSummary({
  summary,
  contactId: _contactId,
  disabled = false,
  className,
}: ContactSummaryProps) {
  // No summary exists yet — show placeholder
  if (!summary) {
    return (
      <Card className={className} data-testid='contact-summary'>
        <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
          <CardTitle className='text-base font-medium'>
            <span className='flex items-center gap-2'>
              <Bot className='h-4 w-4' aria-hidden='true' />
              AI Summary
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p
            className='text-muted-foreground text-sm'
            data-testid='summary-empty-state'
          >
            No AI summary available yet. Request a summary to get AI-generated
            insights about this contact.
          </p>
        </CardContent>
      </Card>
    );
  }

  const attrs = summary.attributes;
  const statusConfig =
    STATUS_CONFIG[attrs.status] || STATUS_CONFIG[ContactSummaryStatus.PENDING];
  const StatusIcon = statusConfig.icon;
  const isAnimated =
    attrs.status === ContactSummaryStatus.GENERATING ||
    attrs.status === ContactSummaryStatus.PENDING;

  // Determine display text (user override takes precedence)
  const displayText =
    attrs.is_user_override && attrs.user_override_text
      ? attrs.user_override_text
      : attrs.summary_text;

  return (
    <Card className={className} data-testid='contact-summary'>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-base font-medium'>
          <span className='flex items-center gap-2'>
            <Bot className='h-4 w-4' aria-hidden='true' />
            AI Summary
          </span>
        </CardTitle>
        <div className='flex items-center gap-2'>
          <Badge
            variant={statusConfig.variant}
            data-testid='summary-status-badge'
          >
            <StatusIcon
              className={`mr-1 h-3 w-3 ${isAnimated ? 'animate-spin' : ''}`}
              aria-hidden='true'
            />
            {statusConfig.label}
          </Badge>
          <Button
            variant='ghost'
            size='icon'
            className='h-7 w-7'
            disabled={disabled || attrs.is_disabled}
            aria-label='Refresh AI summary'
            data-testid='summary-refresh-button'
          >
            <RefreshCw className='h-4 w-4' />
          </Button>
        </div>
      </CardHeader>
      <CardContent className='space-y-3'>
        {/* Summary Text */}
        {displayText ? (
          <div data-testid='summary-text'>
            {attrs.is_user_override && (
              <Badge
                variant='outline'
                className='mb-2'
                data-testid='summary-override-badge'
              >
                User Override
              </Badge>
            )}
            <p className='text-sm leading-relaxed'>{displayText}</p>
          </div>
        ) : (
          <p
            className='text-muted-foreground text-sm'
            data-testid='summary-no-text'
          >
            {attrs.status === ContactSummaryStatus.DISABLED
              ? 'AI summary generation is disabled for this contact.'
              : attrs.status === ContactSummaryStatus.FAILED
                ? 'AI summary generation failed.'
                : attrs.status === ContactSummaryStatus.PENDING
                  ? 'Summary generation is pending…'
                  : attrs.status === ContactSummaryStatus.GENERATING
                    ? 'Summary is being generated…'
                    : 'Summary is unavailable.'}
          </p>
        )}

        {/* Follow-up Suggestions */}
        {attrs.follow_up_suggestions.length > 0 && (
          <div data-testid='summary-suggestions'>
            <p className='text-muted-foreground mb-1 text-xs font-medium tracking-wider uppercase'>
              Suggested Actions
            </p>
            <ul className='space-y-1'>
              {attrs.follow_up_suggestions.map((suggestion, index) => (
                <li
                  key={index}
                  className='text-muted-foreground flex items-start gap-2 text-sm'
                >
                  <span className='text-primary mt-0.5'>•</span>
                  {suggestion}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
