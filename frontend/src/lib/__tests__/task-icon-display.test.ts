/**
 * Tests for the task icon display record and the icon search.
 *
 * The record is typed `Record<TaskIcon, …>`, so a key without an entry does
 * not compile; these tests pin what the type cannot — that each entry renders
 * and has a name a person can search for — and the search rule the picker
 * offers: a trimmed, case-insensitive substring of the name.
 */

import { TASK_ICON_DISPLAY, filterTaskIcons } from '@/lib/task-icon-display';
import { TASK_ICONS } from '@/types/task-icons';

describe('TASK_ICON_DISPLAY', () => {
  it('gives every published key a component and a name', () => {
    TASK_ICONS.forEach(key => {
      const display = TASK_ICON_DISPLAY[key];
      expect(display.Icon).toBeDefined();
      expect(display.label.trim()).not.toBe('');
    });
  });

  it('names each icon differently, and never "No icon"', () => {
    const labels = TASK_ICONS.map(key => TASK_ICON_DISPLAY[key].label);
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels.map(label => label.toLowerCase())).not.toContain('no icon');
  });
});

describe('filterTaskIcons', () => {
  it('offers the whole set, in published order, for an empty or blank query', () => {
    expect(filterTaskIcons('')).toEqual(TASK_ICONS);
    expect(filterTaskIcons('   ')).toEqual(TASK_ICONS);
  });

  it('matches by name', () => {
    expect(filterTaskIcons('shop')).toEqual(['shopping-cart']);
  });

  it('ignores case and surrounding whitespace', () => {
    expect(filterTaskIcons('  TENT ')).toEqual(['tent']);
  });

  it('matches inside a name, not only at its start', () => {
    expect(filterTaskIcons('cart')).toEqual(['shopping-cart']);
  });

  it('keeps published order when several match', () => {
    expect(filterTaskIcons('book')).toEqual(['bookmark', 'book-open']);
  });

  it('offers nothing when no name matches', () => {
    expect(filterTaskIcons('zzz')).toEqual([]);
  });
});
