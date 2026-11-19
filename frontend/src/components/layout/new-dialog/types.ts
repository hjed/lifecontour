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
export type NewEntityId = 'task' | 'journal' | 'contact';

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
  /**
   * This panel is the one shown as the dialog opens. Panels stay mounted while
   * hidden, so only this one may take focus; see `NewEntityType.focusesOnOpen`.
   * The dialog always says; a host rendering a panel on its own may leave it.
   */
  readonly shownOnOpen?: boolean;
}

export interface NewEntityType {
  readonly id: NewEntityId;
  /** Shown on the type switch and used to name the panel. */
  readonly label: string;
  readonly icon: LucideIcon;
  /** The create form for this type. */
  readonly Panel: ComponentType<NewEntityPanelProps>;
  /**
   * The panel puts the cursor in its own first field when shown on open, so
   * the dialog must not move it to its first tabbable control afterwards.
   * Without it the dialog keeps its default open focus.
   */
  readonly focusesOnOpen?: boolean;
}
