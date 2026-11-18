/**
 * Types for the New dialog's entity registry.
 *
 * Each entity the dialog can create is one `NewEntityType`. Adding a type is
 * a new entry in `NEW_ENTITY_TYPES` plus its panel; the dialog itself does not
 * change.
 */

import type { ComponentType } from 'react';
import type { LucideIcon } from 'lucide-react';

/** The entity types the New dialog can create. */
export type NewEntityId = 'journal' | 'contact';

/** What the dialog hands every panel. */
export interface NewEntityPanelProps {
  /** The panel created its entity; the dialog closes. */
  readonly onCreated: () => void;
  /** The user abandoned the panel; the dialog closes. */
  readonly onCancel: () => void;
  /**
   * The panel's save started (`true`) or settled (`false`). While any panel is
   * saving the dialog locks the type switch, so a save that finishes, closes
   * the dialog and navigates cannot discard a draft in another type.
   */
  readonly onBusyChange: (busy: boolean) => void;
}

export interface NewEntityType {
  readonly id: NewEntityId;
  /** Shown on the type switch and used to name the panel. */
  readonly label: string;
  readonly icon: LucideIcon;
  /** The create form for this type. */
  readonly Panel: ComponentType<NewEntityPanelProps>;
}
