'use client';

import { useId } from 'react';
import { Compass } from 'lucide-react';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { BushwalkingData } from '@/types/journals';
import { TypeEditorActions } from './TypeEditorActions';
import { useTypeEditorState } from './useTypeEditorState';

interface BushwalkingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: BushwalkingData;
  readonly onSave?: (data: BushwalkingData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: BushwalkingData) => void;
}

const DEFAULT_DATA: BushwalkingData = {};

const AUSTRALIAN_TRACK_GRADES = [
  {
    grade: 'Grade 1',
    label: 'Grade 1',
    description:
      'No bushwalking experience required. Flat, even surface with no steps or steep sections. Suitable for wheelchair users who have someone to assist them.',
  },
  {
    grade: 'Grade 2',
    label: 'Grade 2',
    description:
      'No bushwalking experience required. The track is a hardened or compacted surface and may have a gentle hill section or steps.',
  },
  {
    grade: 'Grade 3',
    label: 'Grade 3',
    description:
      'Suitable for most ages and fitness levels. Some bushwalking experience recommended. Tracks may have short steep hill sections, a rough surface and many steps.',
  },
  {
    grade: 'Grade 4',
    label: 'Grade 4',
    description:
      'Bushwalking experience recommended. Tracks may be long, rough and very steep. Directional signage may be limited.',
  },
  {
    grade: 'Grade 5',
    label: 'Grade 5',
    description:
      'Very experienced bushwalkers with specialised skills, including navigation and emergency first aid. Tracks are likely to be very rough, very steep and unmarked.',
  },
];

export function BushwalkingTypeEditor({
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
  journalId: _journalId,
}: BushwalkingTypeEditorProps) {
  const baseId = useId();
  const trackGradingFieldId = `${baseId}-track-grading`;
  const {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  } = useTypeEditorState({
    initialData: data ?? DEFAULT_DATA,
    onSave,
    createMode,
    onChange,
  });

  if (!isEditing && !createMode) {
    const hasData = data?.track_grading;

    if (!hasData) {
      return (
        <div className='flex items-center justify-between'>
          <p className='text-muted-foreground text-sm'>
            No bushwalking details provided.
          </p>
          <TypeEditorActions
            isEditing={false}
            onEdit={handleEdit}
            onSave={handleSave}
            onCancel={handleCancel}
          />
        </div>
      );
    }

    const selectedGrade = AUSTRALIAN_TRACK_GRADES.find(
      g => g.grade === data?.track_grading
    );

    return (
      <div
        className={cn('space-y-4 text-sm', className)}
        data-testid={testId || 'bushwalking-type-editor'}
      >
        <div className='grid grid-cols-2 gap-4'>
          {data?.track_grading && (
            <div className='col-span-2'>
              <span className='text-muted-foreground font-medium'>
                Track Grading:{' '}
              </span>
              <span className='font-semibold'>
                {selectedGrade?.label ?? `Grade ${data.track_grading}`}
              </span>
              {selectedGrade && (
                <p className='text-muted-foreground mt-1 text-xs'>
                  {selectedGrade.description}
                </p>
              )}
            </div>
          )}
        </div>
        <TypeEditorActions
          isEditing={false}
          onEdit={handleEdit}
          onSave={handleSave}
          onCancel={handleCancel}
        />
      </div>
    );
  }

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'bushwalking-type-editor'}
    >
      <div className='grid grid-cols-1 gap-6 md:grid-cols-2'>
        {/* Track Grading Dropdown */}
        <div className='space-y-2'>
          <Label
            htmlFor={trackGradingFieldId}
            className='flex items-center gap-2'
          >
            <Compass
              className='text-muted-foreground h-4 w-4'
              aria-hidden='true'
            />
            Australian Track Grading
          </Label>
          <Select
            value={editData.track_grading ?? ''}
            onValueChange={value =>
              setEditData(previous => ({
                ...previous,
                track_grading: value === 'none' ? null : value,
              }))
            }
          >
            <SelectTrigger id={trackGradingFieldId}>
              <SelectValue placeholder='Select track grade...' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value='none'>None</SelectItem>
              {AUSTRALIAN_TRACK_GRADES.map(grade => (
                <SelectItem key={grade.grade} value={grade.grade}>
                  <div className='flex flex-col gap-1 py-1'>
                    <span className='font-medium'>{grade.label}</span>
                    <span className='text-muted-foreground max-w-[280px] text-left text-xs whitespace-normal'>
                      {grade.description}
                    </span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {editData.track_grading && editData.track_grading !== 'none' && (
            <p className='text-muted-foreground text-xs'>
              {
                AUSTRALIAN_TRACK_GRADES.find(
                  g => g.grade === editData.track_grading
                )?.description
              }
            </p>
          )}
        </div>
      </div>

      {!createMode && (
        <TypeEditorActions
          isEditing={isEditing}
          onEdit={handleEdit}
          onSave={handleSave}
          onCancel={handleCancel}
        />
      )}
    </div>
  );
}
