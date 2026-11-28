import { parseTaskListId } from '@/lib/task-list-id';

describe('parseTaskListId', () => {
  it('accepts a positive whole number', () => {
    expect(parseTaskListId('12')).toBe('12');
  });

  it('accepts the largest id the backend can hold', () => {
    expect(parseTaskListId('2147483647')).toBe('2147483647');
  });

  it.each(['abc', '0', '-1', '1.5', '012', '2147483648'])('refuses %s', raw => {
    expect(parseTaskListId(raw)).toBeNull();
  });
});
