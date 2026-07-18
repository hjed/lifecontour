import {
  ActivityTemplateResource,
  ActivityTemplateType,
  JournalType,
} from '@/types/journals';
import type { CanyoningData, CavingData, ClimbingData } from '@/types/journals';

/**
 * Abseiling-derived journal types mapped to their matching template type.
 * These journals always include the consolidated abseiling block, which is
 * the single home for template selection (the per-type editors no longer
 * render their own selector).
 */
const DERIVED_TEMPLATE_TYPES: Partial<
  Record<JournalType, ActivityTemplateType>
> = {
  [JournalType.CANYONING]: ActivityTemplateType.CANYONING,
  [JournalType.CAVING]: ActivityTemplateType.CAVING,
  [JournalType.CLIMBING]: ActivityTemplateType.CLIMBING,
};

/**
 * Template types the consolidated abseiling block should offer for a journal
 * with the given types: the journal's own derived types plus plain abseiling.
 */
export function templateTypesForJournalTypes(
  types: readonly JournalType[]
): ActivityTemplateType[] {
  const derived = types
    .map(type => DERIVED_TEMPLATE_TYPES[type])
    .filter((t): t is ActivityTemplateType => t != null);
  return [...derived, ActivityTemplateType.ABSEILING];
}

export type TemplateTypeFieldUpdates =
  | {
      readonly journalType: JournalType.CANYONING;
      readonly fields: CanyoningData;
    }
  | { readonly journalType: JournalType.CAVING; readonly fields: CavingData }
  | {
      readonly journalType: JournalType.CLIMBING;
      readonly fields: ClimbingData;
    };

/**
 * Type-specific fields a template contributes to its matching type block
 * (e.g. a canyoning template's french grade belongs on the canyoning block).
 * Returns null when the template has no such fields.
 */
export function templateTypeFieldUpdates(
  template: ActivityTemplateResource
): TemplateTypeFieldUpdates | null {
  const attrs = template.attributes;

  switch (attrs.template_type) {
    case ActivityTemplateType.CANYONING: {
      const fields: CanyoningData = {};
      if (attrs.french_grade) fields.french_grade = attrs.french_grade;
      if (attrs.water_gauge_name) {
        fields.water_guage_name = attrs.water_gauge_name;
      }
      if (attrs.is_vertical != null) fields.is_vertical = attrs.is_vertical;
      return Object.keys(fields).length > 0
        ? { journalType: JournalType.CANYONING, fields }
        : null;
    }
    case ActivityTemplateType.CAVING: {
      const fields: CavingData = {};
      if (attrs.is_vertical != null) fields.is_vertical = attrs.is_vertical;
      if (attrs.is_horizontal != null) {
        fields.is_horizontal = attrs.is_horizontal;
      }
      return Object.keys(fields).length > 0
        ? { journalType: JournalType.CAVING, fields }
        : null;
    }
    case ActivityTemplateType.CLIMBING: {
      const fields: ClimbingData = {};
      if (attrs.climbing_type) fields.climbing_type = attrs.climbing_type;
      if (attrs.grade != null) fields.grade = attrs.grade;
      if (attrs.length != null) fields.length = attrs.length;
      return Object.keys(fields).length > 0
        ? { journalType: JournalType.CLIMBING, fields }
        : null;
    }
    default:
      return null;
  }
}
