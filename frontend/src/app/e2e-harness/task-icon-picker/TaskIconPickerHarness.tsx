'use client';

import { useSyncExternalStore, useState } from 'react';

import { TaskIconPicker } from '@/components/tasks/TaskIconPicker';
import type { TaskIcon } from '@/types/task-icons';

const noSubscription = () => () => {};

/**
 * Holds the picker's value and shows what it last handed back.
 *
 * `data-hydrated` is true only once React owns the page, so a spec never acts
 * on the server-rendered markup before its handlers are attached.
 */
export function TaskIconPickerHarness() {
  const [icon, setIcon] = useState<TaskIcon | null>(null);
  const hydrated = useSyncExternalStore(
    noSubscription,
    () => true,
    () => false
  );
  return (
    <div
      data-testid='task-icon-picker-harness'
      data-hydrated={hydrated}
      className='flex max-w-md flex-col gap-4'
    >
      <TaskIconPicker value={icon} onChange={setIcon} />
      <output aria-label='Chosen icon value' className='text-sm'>
        {icon ?? 'none'}
      </output>
    </div>
  );
}
