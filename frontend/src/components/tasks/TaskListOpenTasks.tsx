'use client';

import {
  useId,
  useLayoutEffect,
  useRef,
  type FocusEvent,
  type RefObject,
} from 'react';
import type { ListTaskReadResource } from '@/types/tasks';
import { TaskRow } from './TaskRow';

interface TaskListOpenTasksProps {
  readonly tasks: readonly ListTaskReadResource[];
}

function rowTaskId(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  return target.closest<HTMLElement>('[data-task-id]')?.dataset.taskId ?? null;
}

/**
 * Keeps a keyboard user's place when the task they ticked leaves the list.
 *
 * The refetch after a tick unmounts the focused row, which drops focus to the
 * document body. Focus moves instead to the first row after it that is still
 * there, else the new last row, else the section's heading (shown while it
 * holds focus). It moves only if focus was lost, never away from somewhere
 * the user has since gone: a blur from a row still on the page (a click on
 * blank space, or a move out of the list) forgets it, while the blur of a row
 * being removed, already detached, does not.
 */
function useFocusHandOff(
  tasks: readonly ListTaskReadResource[],
  list: RefObject<HTMLUListElement | null>,
  heading: RefObject<HTMLHeadingElement | null>
) {
  const idsKey = tasks.map(task => task.id).join(' ');
  const focusedTaskId = useRef<string | null>(null);
  const previousTaskIds = useRef<readonly string[]>([]);

  useLayoutEffect(() => {
    const taskIds = idsKey === '' ? [] : idsKey.split(' ');
    const previous = previousTaskIds.current;
    previousTaskIds.current = taskIds;
    const left = focusedTaskId.current;
    if (left === null || taskIds.includes(left)) return;
    focusedTaskId.current = null;

    const active = document.activeElement;
    if (active !== null && active !== document.body) return;

    const successor =
      previous
        .slice(previous.indexOf(left) + 1)
        .find(id => taskIds.includes(id)) ?? taskIds[taskIds.length - 1];
    if (successor === undefined) {
      heading.current?.focus();
      return;
    }
    list.current
      ?.querySelector<HTMLElement>(
        `[data-task-id="${successor}"] [role="checkbox"]`
      )
      ?.focus();
  }, [idsKey, list, heading]);

  return {
    onFocus: (event: FocusEvent) => {
      focusedTaskId.current = rowTaskId(event.target);
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      const next = event.relatedTarget;
      const leftTheList =
        next instanceof Node
          ? !event.currentTarget.contains(next)
          : event.target.isConnected;
      if (leftTheList) focusedTaskId.current = null;
    },
  };
}

export function TaskListOpenTasks({ tasks }: TaskListOpenTasksProps) {
  const headingId = useId();
  const list = useRef<HTMLUListElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const { onFocus, onBlur } = useFocusHandOff(tasks, list, heading);

  return (
    <section
      aria-labelledby={headingId}
      onFocus={onFocus}
      onBlur={onBlur}
      className='border-border border-t'
    >
      <h2
        id={headingId}
        ref={heading}
        tabIndex={-1}
        className='sr-only focus:not-sr-only focus:block focus:py-2 focus:text-sm focus:font-medium'
      >
        Open tasks
      </h2>
      {tasks.length > 0 ? (
        <ul ref={list}>
          {tasks.map(task => (
            <TaskRow key={task.id} task={task} />
          ))}
        </ul>
      ) : (
        <div
          data-testid='task-list-empty'
          className='text-muted-foreground py-10 text-center text-sm'
        >
          <p className='text-foreground text-base font-medium'>
            No open tasks on this list
          </p>
          <p>Tasks you add to this list will appear here.</p>
        </div>
      )}
    </section>
  );
}
