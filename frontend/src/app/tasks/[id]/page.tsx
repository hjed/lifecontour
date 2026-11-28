import type { Metadata } from 'next';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { TaskListPage } from '@/components/tasks/TaskListPage';

export const metadata: Metadata = {
  title: 'Task list',
};

interface TaskListRouteProps {
  readonly params: Promise<{ id: string }>;
}

export default async function TaskListRoute({ params }: TaskListRouteProps) {
  const { id } = await params;

  return (
    <AuthGuard>
      <TaskListPage rawId={id} />
    </AuthGuard>
  );
}
