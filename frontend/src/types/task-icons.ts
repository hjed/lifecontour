/**
 * The fixed set of icons a task or a task list may carry.
 *
 * Values must match the backend `TaskIcon` enum
 * (`core_shared/core_shared/models/tasks/task_icon.py`), in its order — the
 * same keys the OpenAPI `TaskIcon` schema publishes. Like every other backend
 * enum mirrored here, the list is copied rather than generated.
 *
 * The set is **add-only**: a key is never renamed or removed, so the only drift
 * possible is a key the backend has added and this list has not yet. Each key
 * currently matches a `lucide-react` icon name, but the key is ours — the web
 * app maps it to a component, and the stored value never changes if the
 * library renames an icon. `flag` is deliberately absent: the flag is its own
 * on/off marker on every task.
 */
export const TASK_ICONS = [
  'list',
  'clipboard-list',
  'bookmark',
  'star',
  'heart',
  'lightbulb',
  'calendar',
  'house',
  'briefcase',
  'shopping-cart',
  'gift',
  'package',
  'wallet',
  'phone',
  'mail',
  'users',
  'baby',
  'paw-print',
  'party-popper',
  'trophy',
  'plane',
  'luggage',
  'car',
  'bike',
  'map',
  'tent',
  'mountain',
  'leaf',
  'sun',
  'dumbbell',
  'pill',
  'utensils',
  'coffee',
  'shirt',
  'wrench',
  'hammer',
  'book-open',
  'graduation-cap',
  'music',
  'camera',
] as const;

/** One key from {@link TASK_ICONS}. */
export type TaskIcon = (typeof TASK_ICONS)[number];
