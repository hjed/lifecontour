'use client';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { useTaskListOpenTasks } from '@/lib/api/list-tasks';
import { TASK_LIST_NOT_FOUND, useTaskList } from '@/lib/api/task-lists';
import { TaskApiError } from '@/lib/api/tasks';
import { parseTaskListId } from '@/lib/task-list-id';
import { isListTask } from '@/types/tasks';
import { TaskListBreadcrumb } from './TaskListBreadcrumb';
import { TaskListHeader } from './TaskListHeader';
import { TaskListNotFound } from './TaskListNotFound';
import { TaskListOpenTasks } from './TaskListOpenTasks';

interface TaskListPageProps {
  /** The route segment, unchecked: it may not name a list at all. */
  readonly rawId: string;
}

const LOADING_ROWS = 3;

function isListNotFound(error: Error | null): boolean {
  return error instanceof TaskApiError && error.code === TASK_LIST_NOT_FOUND;
}

function TaskListLoading() {
  return (
    <div
      data-testid='task-list-loading'
      role='status'
      aria-busy='true'
      aria-label='Loading list'
      className='space-y-5'
    >
      <Skeleton className='h-5 w-40' />
      <div className='flex items-center gap-4'>
        <Skeleton className='size-11 rounded-lg' />
        <div className='flex-1 space-y-2'>
          <Skeleton className='h-7 w-48' />
          <Skeleton className='h-4 w-24' />
        </div>
      </div>
      <div className='space-y-2'>
        {Array.from({ length: LOADING_ROWS }, (_, index) => (
          <Skeleton key={index} className='h-12 w-full' />
        ))}
      </div>
    </div>
  );
}

export function TaskListPage({ rawId }: TaskListPageProps) {
  const listId = parseTaskListId(rawId);
  const list = useTaskList(listId ?? '');
  const openTasks = useTaskListOpenTasks(listId ?? '');

  if (
    listId === null ||
    isListNotFound(list.error) ||
    isListNotFound(openTasks.error)
  ) {
    return <TaskListNotFound />;
  }

  if (!list.data || !openTasks.data) {
    const failure = list.error ?? openTasks.error;
    if (failure) {
      return (
        <Alert variant='destructive' className='mx-auto max-w-3xl'>
          <AlertDescription>
            Couldn&apos;t load this list: {failure.message}
          </AlertDescription>
        </Alert>
      );
    }
    return (
      <div className='mx-auto max-w-3xl'>
        <TaskListLoading />
      </div>
    );
  }

  const { name, icon } = list.data.data.attributes;
  const tasks = openTasks.data.data.filter(isListTask);

  return (
    <div className='mx-auto max-w-3xl space-y-5'>
      <TaskListBreadcrumb name={name} />
      <TaskListHeader name={name} icon={icon} tasks={tasks} />
      <TaskListOpenTasks tasks={tasks} />
    </div>
  );
}
