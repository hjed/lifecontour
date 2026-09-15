/**
 * Contact AI Summary component.
 *
 * Displays the AI-generated interaction summary with status indicators,
 * follow-up suggestions, user override controls, and a switch to turn AI
 * generation off and back on.
 */

'use client';

import { useId } from 'react';
import { formatDistanceToNow } from 'date-fns';
import {
  Bot,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Ban,
  Pause,
  Sparkles,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  useRefreshContactSummary,
  useUpdateContactSummary,
} from '@/lib/api/contacts';
import {
  ContactSummaryDisabledReason,
  ContactSummaryResource,
  ContactSummaryStatus,
} from '@/types/contacts';

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

/** Badge for a summary paused automatically for low activity. */
const PAUSED_BADGE = {
  label: 'Paused',
  variant: 'outline',
  icon: Pause,
} as const;

interface SummaryGenerationSwitchProps {
  readonly checked: boolean;
  readonly disabled: boolean;
  readonly onCheckedChange: (checked: boolean) => void;
}

/**
 * Switch for the user's choice to generate AI summaries for this contact.
 *
 * Reflects the user's preference rather than the live state: a summary paused
 * for low activity still shows as on, because it resumes by itself.
 */
function SummaryGenerationSwitch({
  checked,
  disabled,
  onCheckedChange,
}: SummaryGenerationSwitchProps) {
  const switchId = useId();

  return (
    <div className='flex items-center justify-between gap-2 border-t pt-3'>
      <Label htmlFor={switchId} className='text-sm font-normal'>
        AI generation
      </Label>
      <Switch
        id={switchId}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        data-testid='summary-generation-switch'
      />
    </div>
  );
}

/**
 * Contact Summary display component.
 *
 * Shows the AI-generated summary, status badge, follow-up suggestions,
 * and user override information.
 */
export function ContactSummary({
  summary,
  contactId,
  disabled = false,
  className,
}: ContactSummaryProps) {
  const { mutate: refreshSummary, isPending: isRefreshing } =
    useRefreshContactSummary(contactId);
  const { mutate: updateSummary, isPending: isUpdating } =
    useUpdateContactSummary(contactId);

  const handleGenerationChange = (checked: boolean) => {
    updateSummary({ is_disabled: !checked });
  };

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
          <SummaryGenerationSwitch
            checked={true}
            disabled={disabled || isUpdating}
            onCheckedChange={handleGenerationChange}
          />
        </CardContent>
      </Card>
    );
  }

  const attrs = summary.attributes;
  const isUserDisabled =
    attrs.disabled_reason === ContactSummaryDisabledReason.USER;
  const isPaused =
    attrs.disabled_reason === ContactSummaryDisabledReason.LOW_ACTIVITY;
  const statusConfig = isPaused
    ? PAUSED_BADGE
    : STATUS_CONFIG[attrs.status] ||
      STATUS_CONFIG[ContactSummaryStatus.PENDING];
  const StatusIcon = statusConfig.icon;
  const isAnimated =
    attrs.status === ContactSummaryStatus.GENERATING ||
    attrs.status === ContactSummaryStatus.PENDING;

  // Determine display text — mirrors backend get_display_text logic:
  // User override text always takes precedence.
  // AI summary_text only shown when status is GENERATED to avoid stale text.
  const displayText =
    attrs.is_user_override && attrs.user_override_text
      ? attrs.user_override_text
      : attrs.status === ContactSummaryStatus.GENERATED
        ? attrs.summary_text
        : null;

  // Show generated_at timestamp only when status is GENERATED and timestamp exists
  const showGeneratedAt =
    attrs.status === ContactSummaryStatus.GENERATED && attrs.generated_at;

  const handleRefresh = () => {
    refreshSummary();
  };

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
            disabled={disabled || isUserDisabled || isRefreshing}
            aria-label='Refresh AI summary'
            data-testid='summary-refresh-button'
            onClick={handleRefresh}
          >
            <RefreshCw
              className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`}
            />
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
            {isPaused
              ? 'AI summary generation is paused — not enough recent activity. It resumes automatically.'
              : attrs.status === ContactSummaryStatus.DISABLED
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

        {/* Generated At Timestamp */}
        {showGeneratedAt && (
          <p
            className='text-muted-foreground text-xs'
            data-testid='summary-generated-at'
          >
            Last generated{' '}
            {formatDistanceToNow(new Date(attrs.generated_at!), {
              addSuffix: true,
            })}
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

        <SummaryGenerationSwitch
          checked={!isUserDisabled}
          disabled={disabled || isUpdating}
          onCheckedChange={handleGenerationChange}
        />
      </CardContent>
    </Card>
  );
}
