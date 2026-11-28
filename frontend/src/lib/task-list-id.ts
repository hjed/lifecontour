/** The largest id the backend's integer column holds; it refuses any above. */
const MAX_TASK_LIST_ID = 2 ** 31 - 1;

/**
 * A list id from a route segment, or `null` when the segment cannot name a
 * list — so the page says "not found" without asking the server.
 */
export function parseTaskListId(raw: string): string | null {
  if (!/^[1-9]\d*$/.test(raw)) return null;
  return Number(raw) <= MAX_TASK_LIST_ID ? raw : null;
}
