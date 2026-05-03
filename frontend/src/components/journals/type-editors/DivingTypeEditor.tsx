'use client';

import { GenericTypeEditorLayout } from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';

interface DivingTypeEditorProps {
  readonly journalId?: string;
  readonly data?: Record<string, never>;
  readonly onSave?: (data: Record<string, never>) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: Record<string, never>) => void;
}

const DEFAULT_DATA: Record<string, never> = {};

export function DivingTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: DivingTypeEditorProps) {
  const { isEditing, handleEdit, handleSave, handleCancel } =
    useTypeEditorState({
      initialData: data ?? DEFAULT_DATA,
      onSave,
      createMode,
      onChange,
    });

  return (
    <GenericTypeEditorLayout
      className={className}
      testId={testId || 'diving-type-editor'}
      createMode={createMode}
      isEditing={isEditing}
      emptyMessage='Diving logbook.'
      summaryItems={[]}
      summaryTestId='diving-summary'
      onEdit={handleEdit}
      onSave={handleSave}
      onCancel={handleCancel}
    >
      <div className='text-muted-foreground text-sm'>
        No additional diving data.
      </div>
    </GenericTypeEditorLayout>
  );
}
