/**
 * Tests for external links utility functions.
 */

import { Activity, Calendar, Users, Link } from 'lucide-react';

import {
  getExternalLinkIcon,
  getExternalLinkLabel,
} from '@/lib/external-links';

describe('getExternalLinkIcon', () => {
  it('returns Activity icon for strava', () => {
    expect(getExternalLinkIcon('strava')).toBe(Activity);
  });

  it('returns Calendar icon for google_calendar', () => {
    expect(getExternalLinkIcon('google_calendar')).toBe(Calendar);
  });

  it('returns Users icon for google_contacts', () => {
    expect(getExternalLinkIcon('google_contacts')).toBe(Users);
  });

  it('returns Link icon for unknown source', () => {
    expect(getExternalLinkIcon('unknown_source')).toBe(Link);
  });
});

describe('getExternalLinkLabel', () => {
  it('returns "Strava" for strava', () => {
    expect(getExternalLinkLabel('strava')).toBe('Strava');
  });

  it('returns "Google Calendar" for google_calendar', () => {
    expect(getExternalLinkLabel('google_calendar')).toBe('Google Calendar');
  });

  it('returns "Google Contacts" for google_contacts', () => {
    expect(getExternalLinkLabel('google_contacts')).toBe('Google Contacts');
  });

  it('returns raw source for unknown source', () => {
    expect(getExternalLinkLabel('custom_system')).toBe('custom_system');
  });
});
