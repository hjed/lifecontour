import { createMockListTaskRead, createMockTaskRead } from '@/test-utils/tasks';
import { isListTask } from '@/types/tasks';

describe('isListTask', () => {
  it('accepts a task on a list', () => {
    expect(isListTask(createMockListTaskRead())).toBe(true);
  });

  it('refuses a journal-only task', () => {
    expect(isListTask(createMockTaskRead({ due_journal_id: 3 }))).toBe(false);
  });
});
