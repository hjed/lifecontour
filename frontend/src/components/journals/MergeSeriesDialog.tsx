'use client';

/**
 * Merge another journal series into this one.
 *
 * The user picks the series to absorb, sets one policy per field for every
 * same-day pair, reviews the preview day by day (unticking any pair they do
 * not want merged) and confirms. The backend re-plans on confirm and answers
 * 409 if the data moved since the preview, in which case the preview is
 * fetched again rather than the dialog closing on a merge that didn't happen.
 */

import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import { Combine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DEFAULT_SERIES_MERGE_POLICIES,
  JournalApiError,
  useJournalSeries,
  useMergeSeries,
  useSeriesMergePreview,
} from '@/lib/api/journals';
import type {
  SeriesFieldPolicy,
  SeriesMergeDay,
  SeriesMergeField,
  SeriesMergePair,
  SeriesMergePlan,
  SeriesMergePolicies,
} from '@/types/journals';

interface MergeSeriesDialogProps {
  readonly destinationSeriesId: string;
  readonly destinationSeriesName: string;
}

const FIELD_LABELS: Record<SeriesMergeField, string> = {
  title: 'Title',
  content: 'Content',
  timing: 'Timing',
  location: 'Location',
  event_description: 'Event description',
};

const FIELDS = Object.keys(FIELD_LABELS) as SeriesMergeField[];

const POLICY_LABELS: Record<SeriesFieldPolicy, string> = {
  destination: 'Keep this series',
  source: 'Use merged-in series',
  combine: 'Combine',
  skip_if_different: 'Skip if different',
};

function policiesFor(field: SeriesMergeField): SeriesFieldPolicy[] {
  return field === 'content'
    ? ['destination', 'source', 'combine', 'skip_if_different']
    : ['destination', 'source', 'skip_if_different'];
}

function pairKey(pair: SeriesMergePair): string {
  return `${pair.source_journal_id}-${pair.destination_journal_id}`;
}

function dayPair(day: SeriesMergeDay): SeriesMergePair | null {
  if (
    day.source_journal_ids.length !== 1 ||
    day.destination_journal_ids.length !== 1
  ) {
    return null;
  }
  return {
    source_journal_id: day.source_journal_ids[0],
    destination_journal_id: day.destination_journal_ids[0],
  };
}

function fieldList(fields: SeriesMergeField[]): string {
  return fields.map(field => FIELD_LABELS[field].toLowerCase()).join(', ');
}

function outcomeText(day: SeriesMergeDay): string {
  switch (day.kind) {
    case 'candidate':
      return day.differing_fields.length
        ? `Will merge; ${fieldList(day.differing_fields)} ${
            day.differing_fields.length === 1 ? 'differs' : 'differ'
          }`
        : 'Will merge';
    case 'skipped':
      return `Not merged: ${fieldList(
        day.skip_reason ? [day.skip_reason] : day.differing_fields
      )} differs`;
    case 'ambiguous':
      return 'Not merged: several journals that day';
    case 'unpaired':
      return day.source_journal_ids.length
        ? 'Moves into this series'
        : 'Already in this series';
    case 'already_shared':
      return 'Already in both series';
    case 'merged':
      return 'Merged';
    case 'excluded':
      return 'Not merged: unticked';
    case 'failed':
      return 'Not merged: the journals could not be merged';
  }
}

function titles(ids: number[], plan: SeriesMergePlan): string {
  return ids.map(id => plan.journals[String(id)]?.title ?? `#${id}`).join(', ');
}

export function MergeSeriesDialog({
  destinationSeriesId,
  destinationSeriesName,
}: MergeSeriesDialogProps) {
  const [open, setOpen] = useState(false);
  const [sourceSeriesId, setSourceSeriesId] = useState<string | null>(null);
  const [policies, setPolicies] = useState<SeriesMergePolicies>(
    DEFAULT_SERIES_MERGE_POLICIES
  );
  const [unticked, setUnticked] = useState<ReadonlySet<string>>(new Set());

  const { data: allSeries } = useJournalSeries();
  const preview = useSeriesMergePreview(
    destinationSeriesId,
    sourceSeriesId,
    policies
  );
  const mergeSeries = useMergeSeries();

  const otherSeries = (allSeries?.data ?? []).filter(
    series => series.id !== destinationSeriesId
  );
  const plan = sourceSeriesId ? preview.data : undefined;
  const confirmedPairs = (plan?.days ?? [])
    .filter(day => day.kind === 'candidate')
    .map(dayPair)
    .filter(
      (pair): pair is SeriesMergePair =>
        pair !== null && !unticked.has(pairKey(pair))
    );

  const reset = () => {
    setSourceSeriesId(null);
    setPolicies(DEFAULT_SERIES_MERGE_POLICIES);
    setUnticked(new Set());
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) reset();
  };

  const togglePair = (pair: SeriesMergePair, checked: boolean) => {
    setUnticked(current => {
      const next = new Set(current);
      if (checked) next.delete(pairKey(pair));
      else next.add(pairKey(pair));
      return next;
    });
  };

  const handleMerge = async () => {
    if (!sourceSeriesId) return;
    try {
      await mergeSeries.mutateAsync({
        destinationSeriesId,
        sourceSeriesId,
        policies,
        pairs: confirmedPairs,
      });
      handleOpenChange(false);
    } catch (error) {
      // The series moved since the preview: show the user what a merge
      // would do now instead of closing on one that didn't happen.
      if (error instanceof JournalApiError && error.status === 409) {
        void preview.refetch();
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          variant='ghost'
          size='sm'
          className='gap-2'
          data-testid='merge-series-button'
        >
          <Combine className='h-4 w-4' />
          Merge a series into this one
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-3xl'>
        <DialogHeader>
          <DialogTitle>Merge a series into {destinationSeriesName}</DialogTitle>
          <DialogDescription>
            Every journal in the chosen series joins this one, and the chosen
            series is deleted. Journals from both series on the same day can be
            merged into this series&apos; journal.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-2'>
          <Label htmlFor='merge-series-source'>Series to merge in</Label>
          <Select
            // '' keeps the Select controlled while showing the placeholder.
            value={sourceSeriesId ?? ''}
            onValueChange={value => setSourceSeriesId(value || null)}
          >
            <SelectTrigger
              id='merge-series-source'
              aria-label='Series to merge in'
              data-testid='merge-series-source'
            >
              <SelectValue placeholder='Choose a series' />
            </SelectTrigger>
            <SelectContent>
              {otherSeries.map(series => (
                <SelectItem key={series.id} value={series.id}>
                  {series.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {sourceSeriesId && (
          <fieldset className='space-y-3'>
            <legend className='text-sm font-medium'>
              For journals merged on the same day
            </legend>
            {FIELDS.map(field => (
              <div
                key={field}
                className='grid gap-1 sm:grid-cols-[10rem_minmax(0,1fr)]'
              >
                <span
                  id={`merge-policy-${field}`}
                  className='text-muted-foreground text-sm'
                >
                  {FIELD_LABELS[field]}
                </span>
                <RadioGroup
                  aria-labelledby={`merge-policy-${field}`}
                  value={policies[field]}
                  onValueChange={value =>
                    setPolicies(current => ({
                      ...current,
                      [field]: value as SeriesFieldPolicy,
                    }))
                  }
                  className='flex flex-wrap gap-x-4 gap-y-1'
                >
                  {policiesFor(field).map(policy => {
                    const id = `merge-policy-${field}-${policy}`;
                    return (
                      <div key={policy} className='flex items-center gap-1.5'>
                        <RadioGroupItem id={id} value={policy} />
                        <Label htmlFor={id} className='font-normal'>
                          {POLICY_LABELS[policy]}
                        </Label>
                      </div>
                    );
                  })}
                </RadioGroup>
              </div>
            ))}
          </fieldset>
        )}

        {sourceSeriesId && preview.isFetching && !plan && (
          <Skeleton
            className='h-24 w-full'
            data-testid='series-merge-loading'
          />
        )}
        {sourceSeriesId && preview.error && (
          <p className='text-destructive text-sm'>{preview.error.message}</p>
        )}

        {plan && (
          <ul
            className='divide-border divide-y rounded-md border'
            aria-label='What the merge will do'
          >
            {plan.days.map(day => {
              const pair = dayPair(day);
              const selectable = day.kind === 'candidate' && pair !== null;
              const label = format(parseISO(day.date), 'd MMM yyyy');
              return (
                <li
                  key={`${day.date}-${day.kind}`}
                  data-testid={`series-merge-day-${day.date}`}
                  className='flex items-start gap-3 p-2 text-sm'
                >
                  {selectable ? (
                    <Checkbox
                      aria-label={`Merge ${label}`}
                      checked={!unticked.has(pairKey(pair))}
                      onCheckedChange={checked =>
                        togglePair(pair, checked === true)
                      }
                      className='mt-0.5'
                    />
                  ) : (
                    <span className='w-4 shrink-0' aria-hidden='true' />
                  )}
                  <div className='min-w-0 flex-1 space-y-0.5'>
                    <div className='font-medium'>{label}</div>
                    <div className='break-words'>
                      {titles(day.source_journal_ids, plan) || '—'}
                      {' → '}
                      {titles(day.destination_journal_ids, plan) || '—'}
                    </div>
                    <div className='text-muted-foreground'>
                      {outcomeText(day)}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <DialogFooter>
          <Button variant='outline' onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant='destructive'
            onClick={handleMerge}
            disabled={!plan || preview.isFetching || mergeSeries.isPending}
            data-testid='confirm-merge-series'
          >
            Merge series
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
