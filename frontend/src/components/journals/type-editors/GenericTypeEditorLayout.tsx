import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { TypeEditorActions } from './TypeEditorActions';

interface GenericTypeEditorLayoutProps {
  readonly className?: string;
  readonly testId: string;
  readonly createMode?: boolean;
  readonly isEditing: boolean;
  readonly emptyMessage: string;
  readonly summaryItems: readonly ReadOnlyTypeSummaryItem[];
  readonly summaryTestId: string;
  readonly onEdit: () => void;
  readonly onSave: () => void;
  readonly onCancel: () => void;
  readonly children?: ReactNode;
  readonly gridClassName?: string;
}

export function compactSummaryItems(
  ...items: Array<ReadOnlyTypeSummaryItem | null>
): ReadOnlyTypeSummaryItem[] {
  return items.filter((item): item is ReadOnlyTypeSummaryItem => item != null);
}

export function GenericTypeEditorLayout({
  className,
  testId,
  createMode = false,
  isEditing,
  emptyMessage,
  summaryItems,
  summaryTestId,
  onEdit,
  onSave,
  onCancel,
  children,
  gridClassName = 'grid grid-cols-1 gap-4 md:grid-cols-2',
}: GenericTypeEditorLayoutProps) {
  if (!isEditing && !createMode) {
    if (summaryItems.length === 0) {
      return (
        <div className='flex items-center justify-between' data-testid={testId}>
          <p className='text-muted-foreground text-sm'>{emptyMessage}</p>
          <TypeEditorActions
            isEditing={false}
            onEdit={onEdit}
            onSave={onSave}
            onCancel={onCancel}
          />
        </div>
      );
    }

    return (
      <div className={cn('space-y-4 text-sm', className)} data-testid={testId}>
        <ReadOnlyTypeSummary items={summaryItems} testId={summaryTestId} />
        <TypeEditorActions
          isEditing={false}
          onEdit={onEdit}
          onSave={onSave}
          onCancel={onCancel}
        />
      </div>
    );
  }

  return (
    <div className={cn('space-y-4', className)} data-testid={testId}>
      <div className={gridClassName}>{children}</div>

      {!createMode && (
        <TypeEditorActions
          isEditing={isEditing}
          onEdit={onEdit}
          onSave={onSave}
          onCancel={onCancel}
        />
      )}
    </div>
  );
}
