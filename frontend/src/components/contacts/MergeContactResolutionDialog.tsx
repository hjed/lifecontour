import React, { useState, useEffect } from 'react';
import type { ContactResource, MergeContactOverrides } from '@/types/contacts';
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
import { ScrollArea } from '@/components/ui/scroll-area';
// Reuse the journal merge resolution shapes for a consistent merge vocabulary.
import type {
  ResolutionChoice,
  FieldResolution,
} from '@/components/journals/MergeResolutionDialog';

export type { ResolutionChoice, FieldResolution };

interface MergeContactResolutionDialogProps {
  readonly survivorContact: ContactResource | null;
  readonly sourceContact: ContactResource | null;
  readonly open: boolean;
  readonly isPending: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly onResolve: (overrides: MergeContactOverrides) => void;
}

/** Override keys the dialog can surface — all string-valued identity fields. */
type TextOverrideField = Exclude<keyof MergeContactOverrides, 'is_favourite'>;

interface Conflict {
  fieldId: TextOverrideField;
  label: string;
  targetValue: string;
  sourceValue: string;
}

/**
 * Scalar identity fields the web resource exposes and the dialog can resolve.
 *
 * `is_favourite` is intentionally excluded — it is a boolean OR-merge with no
 * meaningful "both differ" state (mirrors the backend `_CONFLICT_FIELDS`).
 * `company`/`job_title` are part of the override contract for MCP/API parity but
 * are not exposed on the frontend `ContactResource`, so they cannot be surfaced
 * here; they remain resolvable via MCP/API only. All surfaced fields are short
 * text, so the custom-value control is an `Input` (no multiline field exists).
 */
const CONFLICT_FIELDS: ReadonlyArray<{
  fieldId: TextOverrideField;
  label: string;
}> = [
  { fieldId: 'first_name', label: 'First Name' },
  { fieldId: 'last_name', label: 'Last Name' },
  { fieldId: 'middle_name', label: 'Middle Name' },
  { fieldId: 'nick_name', label: 'Nickname' },
  { fieldId: 'photo_url', label: 'Photo URL' },
];

/**
 * Detect scalar-field conflicts between the survivor and source contacts.
 *
 * A conflict exists only when both sides hold a non-empty value that differs.
 * Returns one {@link Conflict} per differing field, in declaration order.
 */
export function detectContactConflicts(
  survivor: ContactResource,
  source: ContactResource
): Conflict[] {
  const survivorAttrs = survivor.attributes as unknown as Record<
    string,
    unknown
  >;
  const sourceAttrs = source.attributes as unknown as Record<string, unknown>;
  const conflicts: Conflict[] = [];

  for (const { fieldId, label } of CONFLICT_FIELDS) {
    const survivorValue = survivorAttrs[fieldId];
    const sourceValue = sourceAttrs[fieldId];
    const survivorStr =
      survivorValue === null || survivorValue === undefined
        ? ''
        : String(survivorValue);
    const sourceStr =
      sourceValue === null || sourceValue === undefined
        ? ''
        : String(sourceValue);

    if (survivorStr && sourceStr && survivorStr !== sourceStr) {
      conflicts.push({
        fieldId,
        label,
        targetValue: survivorStr,
        sourceValue: sourceStr,
      });
    }
  }

  return conflicts;
}

export function MergeContactResolutionDialog({
  survivorContact,
  sourceContact,
  open,
  isPending,
  onOpenChange,
  onResolve,
}: MergeContactResolutionDialogProps) {
  const [conflicts, setConflicts] = useState<Conflict[] | null>(null);
  const [resolutions, setResolutions] = useState<
    Record<string, FieldResolution>
  >({});

  useEffect(() => {
    if (!survivorContact || !sourceContact) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConflicts(null);
      return;
    }

    const detected = detectContactConflicts(survivorContact, sourceContact);
    const initialResolutions: Record<string, FieldResolution> = {};
    detected.forEach(conflict => {
      initialResolutions[conflict.fieldId] = { choice: 'target' };
    });

    setConflicts(detected);
    setResolutions(prev =>
      Object.keys(prev).length === 0 ? initialResolutions : prev
    );
  }, [survivorContact, sourceContact]);

  const handleResolutionChange = (
    fieldId: string,
    choice: ResolutionChoice
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
    const overrides: MergeContactOverrides = {};

    conflicts.forEach(conflict => {
      const res = resolutions[conflict.fieldId];
      if (!res) return;

      let chosenValue: string | undefined;
      if (res.choice === 'target') {
        chosenValue = conflict.targetValue;
      } else if (res.choice === 'source') {
        chosenValue = conflict.sourceValue;
      } else {
        chosenValue = res.customValue;
      }

      if (chosenValue !== undefined) {
        overrides[conflict.fieldId] = chosenValue;
      }
    });

    onResolve(overrides);
  };

  if (conflicts === null) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>Loading Conflicts</DialogTitle>
            <DialogDescription>
              Comparing contacts for merge conflicts...
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
              No conflicts detected. The contacts will be merged automatically.
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
            The selected source contact has conflicting data with the surviving
            contact. Please choose which values to keep.
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
                          Survivor (Keeps)
                        </Label>
                        <p className='text-muted-foreground whitespace-pre-wrap'>
                          {conflict.targetValue}
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
                          Source (Absorbed)
                        </Label>
                        <p className='text-muted-foreground whitespace-pre-wrap'>
                          {conflict.sourceValue}
                        </p>
                      </div>
                    </div>
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
                          </div>
                        )}
                      </div>
                    </div>
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
