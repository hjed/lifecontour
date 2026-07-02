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

/**
 * Identity fields the web `ContactResource` exposes and the dialog can resolve.
 * A subset of the override contract — see {@link CONFLICT_FIELDS}.
 */
type SurfacedField =
  'first_name' | 'last_name' | 'middle_name' | 'nick_name' | 'photo_url';

interface Conflict {
  fieldId: SurfacedField;
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
  fieldId: SurfacedField;
  label: string;
}> = [
  { fieldId: 'first_name', label: 'First Name' },
  { fieldId: 'last_name', label: 'Last Name' },
  { fieldId: 'middle_name', label: 'Middle Name' },
  { fieldId: 'nick_name', label: 'Nickname' },
  { fieldId: 'photo_url', label: 'Photo URL' },
];

const normalise = (value: string | null | undefined): string => value ?? '';

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
  const conflicts: Conflict[] = [];

  for (const { fieldId, label } of CONFLICT_FIELDS) {
    const survivorStr = normalise(survivor.attributes[fieldId]);
    const sourceStr = normalise(source.attributes[fieldId]);

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

/** A single survivor / source / custom choice within a conflict block. */
function ConflictOption({
  fieldId,
  choice,
  label,
  children,
}: {
  readonly fieldId: string;
  readonly choice: ResolutionChoice;
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  const id = `${choice}-${fieldId}`;
  return (
    <div className='flex items-start space-x-2'>
      <RadioGroupItem
        value={choice}
        id={id}
        data-testid={`radio-${id}`}
        className='mt-1'
      />
      <div className='grid w-full gap-1.5 leading-none'>
        <Label htmlFor={id} className='font-semibold'>
          {label}
        </Label>
        {children}
      </div>
    </div>
  );
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
    setConflicts(detected);
    // Rebuild resolutions to cover exactly the current conflicts: keep the
    // user's prior choice for fields still in conflict, default newly detected
    // fields to the survivor, and drop entries for fields no longer in conflict.
    // This guarantees every conflict always has a selection so handleSubmit
    // never silently skips one when the compared contacts change.
    setResolutions(prev => {
      const next: Record<string, FieldResolution> = {};
      detected.forEach(conflict => {
        next[conflict.fieldId] = prev[conflict.fieldId] ?? { choice: 'target' };
      });
      return next;
    });
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

  const resolveValue = (conflict: Conflict, res: FieldResolution): string => {
    if (res.choice === 'source') return conflict.sourceValue;
    if (res.choice === 'custom') return res.customValue ?? '';
    return conflict.targetValue;
  };

  const handleSubmit = () => {
    if (!conflicts) return;
    const overrides: MergeContactOverrides = {};

    conflicts.forEach(conflict => {
      const res = resolutions[conflict.fieldId];
      if (!res) return;
      overrides[conflict.fieldId] = resolveValue(conflict, res);
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
              const fieldId = conflict.fieldId;
              return (
                <div key={fieldId} className='space-y-3 rounded-md border p-4'>
                  <h4 className='text-sm font-medium'>{conflict.label}</h4>
                  <RadioGroup
                    value={res?.choice}
                    onValueChange={(val: string) =>
                      handleResolutionChange(fieldId, val as ResolutionChoice)
                    }
                    className='space-y-2 text-sm'
                  >
                    <ConflictOption
                      fieldId={fieldId}
                      choice='target'
                      label='Survivor (Keeps)'
                    >
                      <p className='text-muted-foreground whitespace-pre-wrap'>
                        {conflict.targetValue}
                      </p>
                    </ConflictOption>
                    <ConflictOption
                      fieldId={fieldId}
                      choice='source'
                      label='Source (Absorbed)'
                    >
                      <p className='text-muted-foreground whitespace-pre-wrap'>
                        {conflict.sourceValue}
                      </p>
                    </ConflictOption>
                    <ConflictOption
                      fieldId={fieldId}
                      choice='custom'
                      label='Custom Value'
                    >
                      {res?.choice === 'custom' && (
                        <div className='mt-2'>
                          <Input
                            value={res.customValue ?? ''}
                            onChange={e =>
                              handleCustomValueChange(fieldId, e.target.value)
                            }
                            placeholder={`Enter custom ${conflict.label.toLowerCase()}...`}
                          />
                        </div>
                      )}
                    </ConflictOption>
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
