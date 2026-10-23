/**
 * What changed in an aggregate between two reads of it, for the conflict
 * dialog.
 *
 * Coarse on purpose: it names the attributes and relationships that differ,
 * not the values. The `ETag` covers the whole aggregate, so a refused write is
 * as likely to have met a change to a *different* row as to the field the user
 * edited, and the dialog only has to say where to look.
 */

/** The part of a JSON:API document the diff compares. */
export interface AggregateDocument {
  // The API sends `relationships: null` for a contact with none.
  data: { attributes?: object | null; relationships?: object | null };
}

function changedKeys(
  before: object | null | undefined,
  after: object | null | undefined,
  labels: Readonly<Record<string, string>>
): string[] {
  const was = new Map<string, unknown>(Object.entries(before ?? {}));
  const now = new Map<string, unknown>(Object.entries(after ?? {}));
  return Object.keys(labels).filter(
    key => JSON.stringify(was.get(key)) !== JSON.stringify(now.get(key))
  );
}

/**
 * The labels of the parts of an aggregate that differ between two reads.
 *
 * Only the keys `labels` names are compared. A read also carries derived
 * fields outside the aggregate's version — counts, summaries, review
 * suggestions, the timestamps every write moves — and reporting those would
 * point the user at changes no one made to this record.
 *
 * An empty list means nothing the user edits changed — the version moved on a
 * row the client does not show — which the dialog reports as such.
 */
export function diffAggregate(
  before: AggregateDocument | undefined,
  after: AggregateDocument | undefined,
  labels: Readonly<Record<string, string>>
): string[] {
  if (!before || !after) return [];

  const keys = [
    ...changedKeys(before.data.attributes, after.data.attributes, labels),
    ...changedKeys(before.data.relationships, after.data.relationships, labels),
  ];
  return [...new Set(keys.map(key => labels[key] ?? key))];
}
