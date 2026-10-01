import { ExternalLinksDisplay } from 'lifecontour-frontend';
import type { ExternalLink } from '@/lib/external-links';

/** An outdoor journal entry synced from Strava with photos in Immich. */
const journalLinks: ExternalLink[] = [
  {
    source: 'strava',
    url: 'https://www.strava.com/activities/11482930',
    external_id: '11482930',
  },
  {
    source: 'immich_album',
    url: 'https://photos.example.com/albums/3f8c21',
    external_id: '3f8c21',
  },
  {
    source: 'google_calendar',
    url: 'https://calendar.google.com/calendar/event?eid=Y2F0aGVkcmFs',
    external_id: 'cathedral-ranges-traverse',
  },
];

/** A contact mirrored from Google Contacts. */
const contactLinks: ExternalLink[] = [
  {
    source: 'google_contacts',
    url: 'https://contacts.google.com/person/c318',
    external_id: 'c318',
  },
];

/** Gear tracked in Snipe-IT; the maintenance record has no shareable URL. */
const gearLinks: ExternalLink[] = [
  {
    source: 'snipeit',
    url: 'https://assets.example.com/hardware/204',
    external_id: '204',
  },
  {
    source: 'snipeit_maintenance',
    url: null,
    external_id: 'mnt-77',
  },
];

export function JournalEntry() {
  return <ExternalLinksDisplay links={journalLinks} />;
}

export function ContactRecord() {
  return <ExternalLinksDisplay links={contactLinks} />;
}

export function WithUnlinkableSource() {
  return <ExternalLinksDisplay links={gearLinks} />;
}
