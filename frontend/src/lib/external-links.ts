/**
 * External system link types and utilities.
 *
 * Provides TypeScript interfaces, icon mapping, and label helpers
 * for displaying external system links (Strava, Google Calendar,
 * Google Contacts) on journal and contact detail pages.
 */

import {
  Activity,
  Calendar,
  Users,
  Link,
  Package,
  Wrench,
  ClipboardList,
  Camera,
  Image,
  Share2,
  type LucideIcon,
} from 'lucide-react';

/**
 * External system link returned by the API.
 */
export interface ExternalLink {
  /** Integration source identifier */
  source: string;
  /** Clickable URL to external record, or null if not constructable */
  url: string | null;
  /** External system's identifier for the entity */
  external_id: string;
}

/**
 * API response for external links endpoints.
 */
export interface ExternalLinksResponse {
  data: {
    type: string;
    id: string;
    attributes: ExternalLink;
  }[];
}

/** Map of source identifiers to Lucide icon components */
const SOURCE_ICONS: Record<string, LucideIcon> = {
  strava: Activity,
  google_calendar: Calendar,
  google_contacts: Users,
  snipeit: Package,
  snipeit_maintenance: Wrench,
  snipeit_checkout: ClipboardList,
  immich: Camera,
  immich_album: Image,
  immich_shared: Share2,
};

/** Map of source identifiers to human-readable labels */
const SOURCE_LABELS: Record<string, string> = {
  strava: 'Strava',
  google_calendar: 'Google Calendar',
  google_contacts: 'Google Contacts',
  snipeit: 'Snipe-IT Asset',
  snipeit_maintenance: 'Snipe-IT Maintenance',
  snipeit_checkout: 'Snipe-IT Checkout',
  immich: 'Immich Photo',
  immich_album: 'Immich Album',
  immich_shared: 'Immich Shared Link',
};

/**
 * Get the icon component for an external link source.
 *
 * @param source - Integration source identifier
 * @returns Lucide icon component, or Link as fallback
 */
export function getExternalLinkIcon(source: string): LucideIcon {
  return SOURCE_ICONS[source] ?? Link;
}

/**
 * Get the human-readable label for an external link source.
 *
 * @param source - Integration source identifier
 * @returns Display label, or the raw source as fallback
 */
export function getExternalLinkLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}
