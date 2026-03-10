import type { ReactNode } from 'react';
import { Map as MapIcon } from 'lucide-react';
import { RouteSelector } from '@/components/routes/RouteSelector';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import {
  ReadOnlyTypeSummary,
  type ReadOnlyTypeSummaryItem,
} from './ReadOnlyTypeSummary';
import { TypeEditorActions } from './TypeEditorActions';

interface RouteBackedTypeEditorLayoutProps {
  readonly className?: string;
  readonly testId: string;
  readonly createMode?: boolean;
  readonly isEditing: boolean;
  readonly emptyMessage: string;
  readonly summaryItems: readonly ReadOnlyTypeSummaryItem[];
  readonly summaryTestId: string;
  readonly routeFieldId: string;
  readonly routeValue?: string | null;
  readonly onRouteChange: (routeId: string | null) => void;
  readonly routePlaceholder: string;
  readonly onEdit: () => void;
  readonly onSave: () => void;
  readonly onCancel: () => void;
  readonly children?: ReactNode;
  readonly gridClassName?: string;
}

export function buildRouteSummaryItem(
  routeId: string | null | undefined,
  routeName: string | undefined
): ReadOnlyTypeSummaryItem | null {
  if (!routeId) {
    return null;
  }

  return {
    label: 'Route',
    value: routeName ?? routeId,
  };
}

export function compactSummaryItems(
  ...items: Array<ReadOnlyTypeSummaryItem | null>
): ReadOnlyTypeSummaryItem[] {
  return items.filter((item): item is ReadOnlyTypeSummaryItem => item != null);
}

export function RouteBackedTypeEditorLayout({
  className,
  testId,
  createMode = false,
  isEditing,
  emptyMessage,
  summaryItems,
  summaryTestId,
  routeFieldId,
  routeValue,
  onRouteChange,
  routePlaceholder,
  onEdit,
  onSave,
  onCancel,
  children,
  gridClassName = 'grid grid-cols-1 gap-4 md:grid-cols-2',
}: RouteBackedTypeEditorLayoutProps) {
  if (!isEditing && !createMode) {
    if (summaryItems.length === 0) {
      return (
        <div className='flex items-center justify-between'>
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
      <div className={gridClassName}>
        <RouteSelectorField
          fieldId={routeFieldId}
          value={routeValue}
          onChange={onRouteChange}
          placeholder={routePlaceholder}
        />
        {children}
      </div>

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

function RouteSelectorField({
  fieldId,
  value,
  onChange,
  placeholder,
}: {
  readonly fieldId: string;
  readonly value?: string | null;
  readonly onChange: (routeId: string | null) => void;
  readonly placeholder: string;
}) {
  return (
    <div className='space-y-2'>
      <Label htmlFor={fieldId} className='flex items-center gap-2'>
        <MapIcon className='text-muted-foreground h-4 w-4' aria-hidden='true' />
        Route
      </Label>
      <RouteSelector
        id={fieldId}
        value={value ?? null}
        onChange={onChange}
        placeholder={placeholder}
      />
    </div>
  );
}
