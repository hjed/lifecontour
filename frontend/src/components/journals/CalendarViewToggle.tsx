/**
 * CalendarViewToggle - segmented control for switching between
 * List, Month, and Agenda views on the journals page.
 *
 * Uses a radio group pattern for accessibility with proper
 * ARIA roles and keyboard navigation support.
 */

'use client';

import { List, CalendarDays, CalendarRange } from 'lucide-react';
import { cn } from '@/lib/utils';

export type CalendarViewMode = 'list' | 'month' | 'week' | 'day' | 'agenda';

interface CalendarViewToggleProps {
  readonly value: CalendarViewMode;
  readonly onChange: (mode: CalendarViewMode) => void;
  readonly className?: string;
}

const VIEW_OPTIONS: {
  value: CalendarViewMode;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { value: 'list', label: 'List view', icon: List },
  { value: 'month', label: 'Month view', icon: CalendarDays },
  { value: 'week', label: 'Week view', icon: CalendarDays },
  { value: 'day', label: 'Day view', icon: CalendarDays },
  { value: 'agenda', label: 'Agenda view', icon: CalendarRange },
];

export function CalendarViewToggle({
  value,
  onChange,
  className,
}: CalendarViewToggleProps) {
  return (
    <div
      role='radiogroup'
      aria-label='View mode'
      tabIndex={-1}
      className={cn('inline-flex rounded-md border', className)}
      onKeyDown={e => {
        const currentIndex = VIEW_OPTIONS.findIndex(o => o.value === value);
        let nextIndex = currentIndex;

        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          nextIndex = (currentIndex + 1) % VIEW_OPTIONS.length;
        } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          nextIndex =
            (currentIndex - 1 + VIEW_OPTIONS.length) % VIEW_OPTIONS.length;
        } else {
          return; // unhandled key
        }

        e.preventDefault();
        const nextValue = VIEW_OPTIONS[nextIndex].value;
        onChange(nextValue);

        // Move focus to the newly selected radio button
        // Wait for render by using setTimeout since onChange might be batched
        setTimeout(() => {
          if (e.currentTarget) {
            const buttons =
              e.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="radio"]'
              );
            if (buttons[nextIndex]) {
              buttons[nextIndex].focus();
            }
          }
        }, 0);
      }}
    >
      {VIEW_OPTIONS.map(option => {
        const Icon = option.icon;
        const isSelected = value === option.value;

        return (
          <button
            key={option.value}
            role='radio'
            aria-checked={isSelected}
            aria-label={option.label}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => onChange(option.value)}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-medium transition-colors',
              'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none',
              'first:rounded-l-md last:rounded-r-md',
              isSelected
                ? 'bg-primary text-primary-foreground'
                : 'bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
            )}
          >
            <Icon className='h-4 w-4' />
            <span className='sr-only sm:not-sr-only'>
              {option.label.replace(' view', '')}
            </span>
          </button>
        );
      })}
    </div>
  );
}
