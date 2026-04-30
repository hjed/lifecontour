'use client';

import { useCallback } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import type { AbseilPitch } from '@/types/journals';

const VALID_ANCHOR_LOCATIONS = ['TR', 'TL', 'Centre'];
const VALID_ANCHOR_TYPES = [
  'chains',
  'double bolt',
  'single bolt',
  'sling on tree',
  'sling on log',
  'sling on boulder',
  'sling on bollard',
  'artificial removable',
];

interface PitchEditorProps {
  readonly pitches?: AbseilPitch[];
  readonly onChange: (pitches: AbseilPitch[]) => void;
  readonly isEditing?: boolean;
  readonly className?: string;
}

export function PitchEditor({
  pitches = [],
  onChange,
  isEditing = true,
  className,
}: PitchEditorProps) {
  const handleAddPitch = useCallback(() => {
    const nextPitchNumber =
      pitches.length > 0
        ? Math.max(...pitches.map(p => p.pitch_number)) + 1
        : 1;

    onChange([
      ...pitches,
      {
        pitch_number: nextPitchNumber,
        height: null,
        anchor_location: null,
        anchor_type: null,
        did_rescue: null,
        did_setup: null,
      },
    ]);
  }, [pitches, onChange]);

  const handleRemovePitch = useCallback(
    (index: number) => {
      const newPitches = [...pitches];
      newPitches.splice(index, 1);
      onChange(newPitches);
    },
    [pitches, onChange]
  );

  const handleUpdatePitch = useCallback(
    (
      index: number,
      field: keyof AbseilPitch,
      value: AbseilPitch[keyof AbseilPitch]
    ) => {
      const newPitches = [...pitches];
      newPitches[index] = { ...newPitches[index], [field]: value };
      onChange(newPitches);
    },
    [pitches, onChange]
  );

  if (!isEditing) {
    if (pitches.length === 0) {
      return null;
    }

    return (
      <div
        className={cn('space-y-2 text-sm', className)}
        data-testid='pitch-editor-readonly'
      >
        <div className='text-muted-foreground mb-2 font-medium'>
          Pitches ({pitches.length})
        </div>
        <div className='divide-y overflow-hidden rounded-md border'>
          {pitches.map((pitch, idx) => (
            <div
              key={pitch.id ?? `temp-${idx}`}
              className='hover:bg-muted/50 grid grid-cols-6 items-center gap-2 p-2'
            >
              <div className='font-medium'>#{pitch.pitch_number}</div>
              <div className='text-muted-foreground'>
                {pitch.height != null ? `${pitch.height}m` : '-'}
              </div>
              <div className='truncate'>{pitch.anchor_location || '-'}</div>
              <div className='col-span-2 truncate'>
                {pitch.anchor_type || '-'}
              </div>
              <div className='flex gap-2 text-xs'>
                {pitch.did_setup && (
                  <span className='bg-primary/10 text-primary rounded px-1.5'>
                    Setup
                  </span>
                )}
                {pitch.did_rescue && (
                  <span className='bg-destructive/10 text-destructive rounded px-1.5'>
                    Rescue
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-4', className)} data-testid='pitch-editor'>
      <div className='flex items-center justify-between'>
        <h4 className='text-sm leading-none font-medium'>Abseil Pitches</h4>
        <Button
          type='button'
          variant='outline'
          size='sm'
          onClick={handleAddPitch}
          className='flex h-8 items-center gap-1'
          data-testid='add-pitch-button'
        >
          <Plus className='h-4 w-4' />
          Add Pitch
        </Button>
      </div>

      {pitches.length > 0 ? (
        <div className='bg-card overflow-hidden rounded-md border'>
          <div className='bg-muted/50 text-muted-foreground grid grid-cols-[60px_1fr_1fr_2fr_60px_60px_40px] items-center gap-2 p-3 text-xs font-medium'>
            <div>Pitch #</div>
            <div>Height (m)</div>
            <div>Location</div>
            <div>Anchor Type</div>
            <div className='text-center'>Setup?</div>
            <div className='text-center'>Rescue?</div>
            <div></div>
          </div>
          <div className='divide-y'>
            {pitches.map((pitch, index) => {
              return (
                <div
                  key={pitch.id ?? `temp-${index}`}
                  className='grid grid-cols-[60px_1fr_1fr_2fr_60px_60px_40px] items-center gap-2 p-2'
                  data-testid={`pitch-row-${index}`}
                >
                  <Input
                    type='number'
                    min={1}
                    value={pitch.pitch_number}
                    onChange={e =>
                      handleUpdatePitch(
                        index,
                        'pitch_number',
                        e.target.value === ''
                          ? 0
                          : Number.parseInt(e.target.value, 10)
                      )
                    }
                    className='h-8 px-2'
                    aria-label={`Pitch number for row ${index + 1}`}
                  />

                  <Input
                    type='number'
                    min={0}
                    value={pitch.height ?? ''}
                    onChange={e =>
                      handleUpdatePitch(
                        index,
                        'height',
                        e.target.value === ''
                          ? null
                          : Number.parseInt(e.target.value, 10)
                      )
                    }
                    className='h-8 px-2'
                    placeholder='Height'
                    aria-label={`Height for pitch ${pitch.pitch_number}`}
                  />

                  <Select
                    value={pitch.anchor_location ?? ''}
                    onValueChange={value =>
                      handleUpdatePitch(
                        index,
                        'anchor_location',
                        value === 'none' ? null : value
                      )
                    }
                  >
                    <SelectTrigger
                      className='h-8 px-2'
                      aria-label={`Location for pitch ${pitch.pitch_number}`}
                    >
                      <SelectValue placeholder='-' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='none'>- None -</SelectItem>
                      {VALID_ANCHOR_LOCATIONS.map(loc => (
                        <SelectItem key={loc} value={loc}>
                          {loc}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Select
                    value={pitch.anchor_type ?? ''}
                    onValueChange={value =>
                      handleUpdatePitch(
                        index,
                        'anchor_type',
                        value === 'none' ? null : value
                      )
                    }
                  >
                    <SelectTrigger
                      className='h-8 px-2'
                      aria-label={`Anchor type for pitch ${pitch.pitch_number}`}
                    >
                      <SelectValue placeholder='-' />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value='none'>- None -</SelectItem>
                      {VALID_ANCHOR_TYPES.map(type => (
                        <SelectItem key={type} value={type}>
                          {type}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className='flex justify-center'>
                    <Checkbox
                      checked={pitch.did_setup ?? false}
                      onCheckedChange={checked =>
                        handleUpdatePitch(index, 'did_setup', checked === true)
                      }
                      aria-label={`Setup for pitch ${pitch.pitch_number}`}
                      data-testid={`pitch-setup-${index}`}
                    />
                  </div>

                  <div className='flex justify-center'>
                    <Checkbox
                      checked={pitch.did_rescue ?? false}
                      onCheckedChange={checked =>
                        handleUpdatePitch(index, 'did_rescue', checked === true)
                      }
                      aria-label={`Rescue for pitch ${pitch.pitch_number}`}
                      data-testid={`pitch-rescue-${index}`}
                    />
                  </div>

                  <div className='flex justify-center'>
                    <Button
                      type='button'
                      variant='ghost'
                      size='icon'
                      className='text-muted-foreground hover:text-destructive h-8 w-8'
                      onClick={() => handleRemovePitch(index)}
                      aria-label={`Remove pitch ${pitch.pitch_number}`}
                      data-testid={`remove-pitch-${index}`}
                    >
                      <Trash2 className='h-4 w-4' />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className='text-muted-foreground bg-muted/20 rounded-md border border-dashed p-4 text-center text-sm'>
          No pitches added. Click &quot;Add Pitch&quot; to record abseil
          details.
        </div>
      )}
    </div>
  );
}
