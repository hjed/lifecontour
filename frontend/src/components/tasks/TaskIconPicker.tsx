'use client';

/**
 * Chooses a task's or a list's icon from the fixed set, or none.
 *
 * A radio group rather than a listbox or a menu: the choice is one of a fixed
 * set or nothing, so Radix supplies the roving tab stop and the arrow keys,
 * and "No icon" is the first radio rather than a separate clear button. The
 * group is named through `aria-labelledby` on a plain `<span>`, not a
 * `<fieldset>`, which would wrap it in a second group of the same name (the
 * rule `AttachTaskDialog` documents).
 *
 * Each arrow key moves the choice and calls `onChange`, as radios do, so a
 * caller commits the value on its form's submit rather than on every change.
 */

import { useId, useState } from 'react';
import { Ban, Check } from 'lucide-react';
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui';

import { TaskIconGlyph } from '@/components/tasks/TaskIconGlyph';
import { Input } from '@/components/ui/input';
import { RadioGroup } from '@/components/ui/radio-group';
import { TASK_ICON_DISPLAY, filterTaskIcons } from '@/lib/task-icon-display';
import { cn } from '@/lib/utils';
import { TASK_ICONS, type TaskIcon } from '@/types/task-icons';

const NO_ICON_VALUE = 'none';
const NO_ICON_LABEL = 'No icon';

interface TaskIconPickerProps {
  readonly value: TaskIcon | null;
  readonly onChange: (icon: TaskIcon | null) => void;
  readonly disabled?: boolean;
}

export function TaskIconPicker({
  value,
  onChange,
  disabled = false,
}: TaskIconPickerProps) {
  const labelId = useId();
  const gridId = useId();
  const [query, setQuery] = useState('');

  const offered = filterTaskIcons(query);
  const chosen = value ? TASK_ICON_DISPLAY[value].label : null;

  return (
    <div className='flex min-w-0 flex-col gap-2'>
      <span id={labelId} className='text-sm font-medium'>
        Icon
      </span>
      <div className='border-input min-w-0 overflow-hidden rounded-lg border'>
        <div className='border-input has-[input:focus-visible]:ring-ring/50 flex items-center gap-2 border-b px-2 has-[input:focus-visible]:ring-3 has-[input:focus-visible]:ring-inset'>
          <Input
            type='search'
            aria-label='Search icons'
            aria-controls={gridId}
            placeholder='Search icons'
            value={query}
            onChange={event => setQuery(event.target.value)}
            disabled={disabled}
            className='h-11 min-w-0 flex-1 border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent'
          />
          <span
            role='status'
            className='text-muted-foreground max-w-1/2 text-right text-xs wrap-anywhere'
          >
            {situation(query, offered.length)}
          </span>
        </div>
        <RadioGroup
          id={gridId}
          aria-labelledby={labelId}
          value={value ?? NO_ICON_VALUE}
          onValueChange={next =>
            onChange(TASK_ICONS.find(key => key === next) ?? null)
          }
          disabled={disabled}
          className='grid max-h-40 grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))] gap-1 overflow-y-auto p-1.5'
        >
          <IconTile value={NO_ICON_VALUE} label={NO_ICON_LABEL}>
            <Ban aria-hidden='true' className='size-5' />
          </IconTile>
          {offered.map(key => (
            <IconTile
              key={key}
              value={key}
              label={TASK_ICON_DISPLAY[key].label}
            >
              <TaskIconGlyph icon={key} className='size-5' />
            </IconTile>
          ))}
        </RadioGroup>
      </div>
      <p className='text-muted-foreground text-sm'>
        {chosen ? `Chosen: ${chosen}` : 'No icon chosen'}
      </p>
    </div>
  );
}

/** What the grid holds right now, said in every state. */
function situation(query: string, count: number): string {
  if (count === 0) return `No icons match "${query.trim()}"`;
  return count === 1 ? '1 icon' : `${count} icons`;
}

function IconTile({
  value,
  label,
  children,
}: {
  readonly value: string;
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <RadioGroupPrimitive.Item
      value={value}
      aria-label={label}
      title={label}
      className={cn(
        'group/tile relative flex size-11 items-center justify-center justify-self-center rounded-md outline-none',
        'bg-background text-foreground hover:not-data-checked:bg-muted',
        'focus-visible:outline-ring focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-solid',
        'data-checked:bg-primary data-checked:text-primary-foreground data-checked:ring-primary data-checked:ring-offset-background data-checked:ring-2 data-checked:ring-offset-1',
        'disabled:cursor-not-allowed disabled:opacity-50'
      )}
    >
      {children}
      <Check
        aria-hidden='true'
        className='absolute top-0.5 right-0.5 hidden size-3 group-data-checked/tile:block'
      />
    </RadioGroupPrimitive.Item>
  );
}
