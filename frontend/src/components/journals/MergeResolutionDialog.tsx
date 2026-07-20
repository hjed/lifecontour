import React, { useState, useEffect } from 'react';
import type { JournalResource, MergeOverrides } from '@/types/journals';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';

interface MergeResolutionDialogProps {
  readonly targetJournal: JournalResource | null;
  readonly sourceJournal: JournalResource | null;
  readonly open: boolean;
  readonly isPending: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onResolve: (overrides: MergeOverrides) => void;
}

interface Conflict {
  fieldId: string;
  label: string;
  targetValue: unknown;
  sourceValue: unknown;
  isText: boolean;
  /** Human-readable stand-ins for opaque values (e.g. a calendar name). */
  targetDisplay?: string;
  sourceDisplay?: string;
}

/** Field names whose humanised form is not just a title-cased identifier. */
const FIELD_LABELS: Record<string, string> = {
  calendar_id: 'Calendar',
};

/** Turn `MOOD_RATING` / `mood_value` into `Mood Rating` / `Mood Value`. */
function humanise(segment: string): string {
  return segment
    .split('_')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

function buildTypeDataLabel(typeKey: string, fieldKey: string): string {
  const field = FIELD_LABELS[fieldKey] ?? humanise(fieldKey);
  return `${humanise(typeKey)} — ${field}`;
}

/**
 * Resolve a calendar id to its name using the calendar embedded on the journal
 * that the value came from. Falls back to the raw id when there is no embedded
 * calendar, or when it describes a different calendar.
 */
function resolveCalendarName(
  journal: JournalResource | null,
  value: unknown
): string | undefined {
  const calendar = journal?.attributes?.calendar;
  if (!calendar?.name || calendar.id !== String(value)) return undefined;
  return calendar.name;
}

export type ResolutionChoice = 'target' | 'source' | 'custom';
export interface FieldResolution {
  choice: ResolutionChoice;
  customValue?: string;
}

export function MergeResolutionDialog({
  targetJournal,
  sourceJournal,
  open,
  isPending,
  onOpenChange,
  onResolve,
}: MergeResolutionDialogProps) {
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);
  const [resolutions, setResolutions] = useState<
    Record<string, FieldResolution>
  >({});

  useEffect(() => {
    if (!targetJournal || !sourceJournal) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConflicts(null);
      return;
    }

    const target = targetJournal.attributes;
    const source = sourceJournal.attributes;
    const newConflicts: Conflict[] = [];
    const initialResolutions: Record<
      string,
      { choice: 'target' | 'source' | 'custom' }
    > = {};

    // Determine default choice based on precedence (target manual beats source event, etc)
    // We can just default to 'target' for simplicity on the UI, but user can change it.
    const defaultChoice = 'target';

    // Title
    if (source.title && target.title && source.title !== target.title) {
      newConflicts.push({
        fieldId: 'title',
        label: 'Title',
        targetValue: target.title,
        sourceValue: source.title,
        isText: true,
      });
      initialResolutions['title'] = { choice: defaultChoice };
    }

    // Content
    if (source.content && target.content && source.content !== target.content) {
      newConflicts.push({
        fieldId: 'content',
        label: 'Content',
        targetValue: target.content,
        sourceValue: source.content,
        isText: true,
      });
      initialResolutions['content'] = { choice: defaultChoice };
    }

    // Event Date Range
    const sourceDateStr = source.event_date_range
      ? `${source.event_date_range.start}-${source.event_date_range.end}`
      : null;
    const targetDateStr = target.event_date_range
      ? `${target.event_date_range.start}-${target.event_date_range.end}`
      : null;
    if (sourceDateStr && targetDateStr && sourceDateStr !== targetDateStr) {
      newConflicts.push({
        fieldId: 'event_date_range',
        label: 'Event Dates',
        targetValue: target.event_date_range,
        sourceValue: source.event_date_range,
        isText: false,
      });
      initialResolutions['event_date_range'] = { choice: defaultChoice };
    }

    // Type Data
    if (source.type_data && target.type_data) {
      Object.keys(source.type_data).forEach(typeKey => {
        const tKey = typeKey as keyof typeof target.type_data;
        const targetObj = target.type_data?.[tKey];
        const sourceObj = source.type_data?.[tKey];

        if (targetObj && sourceObj) {
          Object.keys(sourceObj).forEach(fieldKey => {
            const sVal = (sourceObj as Record<string, unknown>)[fieldKey];
            const tVal = (targetObj as Record<string, unknown>)[fieldKey];
            if (
              sVal !== null &&
              tVal !== null &&
              sVal !== undefined &&
              tVal !== undefined &&
              sVal !== tVal
            ) {
              const fieldId = `type_data.${typeKey}.${fieldKey}`;
              const isCalendar = fieldKey === 'calendar_id';
              newConflicts.push({
                fieldId,
                label: buildTypeDataLabel(typeKey, fieldKey),
                targetValue: tVal,
                sourceValue: sVal,
                // A calendar id is an opaque identifier, not free text the
                // user should be able to hand-edit.
                isText: typeof sVal === 'string' && !isCalendar,
                targetDisplay: isCalendar
                  ? resolveCalendarName(targetJournal, tVal)
                  : undefined,
                sourceDisplay: isCalendar
                  ? resolveCalendarName(sourceJournal, sVal)
                  : undefined,
              });
              initialResolutions[fieldId] = { choice: defaultChoice };
            }
          });
        }
      });
    }

    setConflicts(newConflicts);
    // Only set initial resolutions if we haven't resolved them yet

    setResolutions(prev =>
      Object.keys(prev).length === 0 ? initialResolutions : prev
    );
  }, [targetJournal, sourceJournal]);

  const handleResolutionChange = (
    fieldId: string,
    choice: 'target' | 'source' | 'custom'
  ) => {
    setResolutions(prev => ({
      ...prev,
      [fieldId]: { ...prev[fieldId], choice },
    }));
  };

  const handleCustomValueChange = (fieldId: string, customValue: string) => {
    setResolutions(prev => ({
      ...prev,
      [fieldId]: { ...prev[fieldId], customValue },
    }));
  };

  const handleSubmit = () => {
    if (!conflicts) return;
    const overrides: MergeOverrides = {};

    conflicts.forEach(conflict => {
      const res = resolutions[conflict.fieldId];
      if (!res) return;

      let chosenValue: unknown = undefined;
      if (res.choice === 'target') {
        chosenValue = conflict.targetValue;
      } else if (res.choice === 'source') {
        chosenValue = conflict.sourceValue;
      } else if (res.choice === 'custom') {
        chosenValue = res.customValue;
      }

      if (chosenValue !== undefined) {
        if (conflict.fieldId.startsWith('type_data.')) {
          const parts = conflict.fieldId.split('.');
          const typeKey = parts[1];
          const fieldKey = parts[2];
          if (!overrides.type_data) overrides.type_data = {};
          if (!overrides.type_data[typeKey]) overrides.type_data[typeKey] = {};
          overrides.type_data[typeKey][fieldKey] = chosenValue;
        } else {
          // @ts-expect-error dynamic assignment
          overrides[conflict.fieldId] = chosenValue;
        }
      }
    });

    onResolve(overrides);
  };

  const renderConflictValue = (val: unknown, display?: string) => {
    if (display) return display;
    if (val === null || val === undefined) return 'None';
    if (typeof val === 'object') {
      const v = val as { start?: string; end?: string };
      if (v.start && v.end) {
        return `${new Date(v.start).toLocaleString()} - ${new Date(v.end).toLocaleString()}`;
      }
      return JSON.stringify(val);
    }
    return String(val);
  };

  // If there are no conflicts, we shouldn't really be in this dialog,
  // but if we are, we can just show a message.
  if (conflicts === null) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>Loading Conflicts</DialogTitle>
            <DialogDescription>
              Comparing journals for merge conflicts...
            </DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    );
  }

  if (conflicts.length === 0) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>Confirm Merge</DialogTitle>
            <DialogDescription>
              No conflicts detected. The journals will be merged automatically.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={isPending}
              className='bg-destructive hover:bg-destructive/90 text-destructive-foreground'
            >
              {isPending ? 'Merging...' : 'Merge'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='flex max-h-[80vh] flex-col sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>Resolve Merge Conflicts</DialogTitle>
          <DialogDescription>
            The selected source journal has conflicting data with the target
            journal. Please choose which values to keep.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className='my-4 flex-1 overflow-y-auto pr-4'>
          <div className='space-y-6'>
            {conflicts.map(conflict => {
              const res = resolutions[conflict.fieldId];
              return (
                <div
                  key={conflict.fieldId}
                  className='space-y-3 rounded-md border p-4'
                >
                  <h4 className='text-sm font-medium'>{conflict.label}</h4>
                  <RadioGroup
                    value={res?.choice}
                    onValueChange={(val: string) =>
                      handleResolutionChange(
                        conflict.fieldId,
                        val as ResolutionChoice
                      )
                    }
                    className='space-y-2 text-sm'
                  >
                    <div className='flex items-start space-x-2'>
                      <RadioGroupItem
                        value='target'
                        id={`target-${conflict.fieldId}`}
                        data-testid={`radio-target-${conflict.fieldId}`}
                        className='mt-1'
                      />
                      <div className='grid gap-1.5 leading-none'>
                        <Label
                          htmlFor={`target-${conflict.fieldId}`}
                          className='font-semibold'
                        >
                          Target (Current)
                        </Label>
                        <p className='text-muted-foreground whitespace-pre-wrap'>
                          {renderConflictValue(
                            conflict.targetValue,
                            conflict.targetDisplay
                          )}
                        </p>
                      </div>
                    </div>
                    <div className='flex items-start space-x-2'>
                      <RadioGroupItem
                        value='source'
                        id={`source-${conflict.fieldId}`}
                        data-testid={`radio-source-${conflict.fieldId}`}
                        className='mt-1'
                      />
                      <div className='grid gap-1.5 leading-none'>
                        <Label
                          htmlFor={`source-${conflict.fieldId}`}
                          className='font-semibold'
                        >
                          Source (Incoming)
                        </Label>
                        <p className='text-muted-foreground whitespace-pre-wrap'>
                          {renderConflictValue(
                            conflict.sourceValue,
                            conflict.sourceDisplay
                          )}
                        </p>
                      </div>
                    </div>
                    {conflict.isText && (
                      <div className='flex items-start space-x-2'>
                        <RadioGroupItem
                          value='custom'
                          id={`custom-${conflict.fieldId}`}
                          data-testid={`radio-custom-${conflict.fieldId}`}
                          className='mt-1'
                        />
                        <div className='grid w-full gap-1.5 leading-none'>
                          <Label
                            htmlFor={`custom-${conflict.fieldId}`}
                            className='font-semibold'
                          >
                            Custom Value
                          </Label>
                          {res?.choice === 'custom' && (
                            <div className='mt-2'>
                              {conflict.fieldId === 'content' ? (
                                <Textarea
                                  value={res.customValue ?? ''}
                                  onChange={e =>
                                    handleCustomValueChange(
                                      conflict.fieldId,
                                      e.target.value
                                    )
                                  }
                                  placeholder='Enter custom combined content...'
                                  className='min-h-[100px]'
                                />
                              ) : (
                                <Input
                                  value={res.customValue ?? ''}
                                  onChange={e =>
                                    handleCustomValueChange(
                                      conflict.fieldId,
                                      e.target.value
                                    )
                                  }
                                  placeholder={`Enter custom ${conflict.label.toLowerCase()}...`}
                                />
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </RadioGroup>
                </div>
              );
            })}
          </div>
        </ScrollArea>

        <DialogFooter className='pt-2'>
          <Button
            variant='outline'
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isPending}
            className='bg-primary text-primary-foreground'
          >
            {isPending ? 'Merging...' : 'Resolve and Merge'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
