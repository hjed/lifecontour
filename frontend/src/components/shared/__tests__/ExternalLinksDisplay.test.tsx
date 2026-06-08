/**
 * Tests for ExternalLinksDisplay component.
 */

import { render, screen } from '@testing-library/react';

import { ExternalLinksDisplay } from '../ExternalLinksDisplay';
import type { ExternalLink } from '@/lib/external-links';

describe('ExternalLinksDisplay', () => {
  it('renders nothing when no links provided', () => {
    const { container } = render(<ExternalLinksDisplay links={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when links is empty array', () => {
    const { container } = render(<ExternalLinksDisplay links={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders Strava link with icon and clickable URL', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/123',
        external_id: '123',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-strava');
    expect(linkElement).toBeInTheDocument();
    expect(linkElement).toHaveAttribute(
      'href',
      'https://www.strava.com/activities/123'
    );
    expect(screen.getByText('Strava')).toBeInTheDocument();
  });

  it('renders Google Calendar link with icon and clickable URL', () => {
    const links: ExternalLink[] = [
      {
        source: 'google_calendar',
        url: 'https://calendar.google.com/calendar/event?eid=abc123',
        external_id: 'evt123',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-google_calendar');
    expect(linkElement).toBeInTheDocument();
    expect(linkElement).toHaveAttribute(
      'href',
      'https://calendar.google.com/calendar/event?eid=abc123'
    );
    expect(screen.getByText('Google Calendar')).toBeInTheDocument();
  });

  it('renders Google Contacts link with icon and clickable URL', () => {
    const links: ExternalLink[] = [
      {
        source: 'google_contacts',
        url: 'https://contacts.google.com/person/c123',
        external_id: 'c123',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-google_contacts');
    expect(linkElement).toBeInTheDocument();
    expect(linkElement).toHaveAttribute(
      'href',
      'https://contacts.google.com/person/c123'
    );
    expect(screen.getByText('Google Contacts')).toBeInTheDocument();
  });

  it('renders icon without link when URL is null', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: null,
        external_id: 'athlete-123',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const badge = screen.getByTestId('external-link-strava');
    expect(badge).toBeInTheDocument();
    // Badge without link should not be an anchor element
    expect(badge.tagName).not.toBe('A');
    expect(screen.getByText('Strava')).toBeInTheDocument();
  });

  it('renders multiple links simultaneously', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/456',
        external_id: '456',
      },
      {
        source: 'google_calendar',
        url: 'https://calendar.google.com/calendar/event?eid=def',
        external_id: 'evt456',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    expect(screen.getByTestId('external-link-strava')).toBeInTheDocument();
    expect(
      screen.getByTestId('external-link-google_calendar')
    ).toBeInTheDocument();
    expect(screen.getByText('Strava')).toBeInTheDocument();
    expect(screen.getByText('Google Calendar')).toBeInTheDocument();
  });

  it('opens links in new tab with proper rel attributes', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/789',
        external_id: '789',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-strava');
    expect(linkElement).toHaveAttribute('target', '_blank');
    expect(linkElement).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('has proper accessibility labels', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/100',
        external_id: '100',
      },
      {
        source: 'google_contacts',
        url: null,
        external_id: 'person-1',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    // Clickable link should have aria-label
    const stravaLink = screen.getByTestId('external-link-strava');
    expect(stravaLink).toHaveAttribute('aria-label', 'Open in Strava');
  });

  it('renders section container with data-testid', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/1',
        external_id: '1',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    expect(screen.getByTestId('external-links-section')).toBeInTheDocument();
  });

  it('renders "Linked Systems" header', () => {
    const links: ExternalLink[] = [
      {
        source: 'strava',
        url: 'https://www.strava.com/activities/1',
        external_id: '1',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    expect(screen.getByText('Linked Systems')).toBeInTheDocument();
  });

  it('renders Immich album link with clickable URL and accessible label', () => {
    const links: ExternalLink[] = [
      {
        source: 'immich_album',
        url: 'https://immich.example.com/albums/album-uuid',
        external_id: 'album-uuid',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-immich_album');
    expect(linkElement).toHaveAttribute(
      'href',
      'https://immich.example.com/albums/album-uuid'
    );
    expect(linkElement).toHaveAttribute('target', '_blank');
    expect(linkElement).toHaveAttribute('rel', 'noopener noreferrer');
    expect(linkElement).toHaveAttribute('aria-label', 'Open in Immich Album');
    expect(screen.getByText('Immich Album')).toBeInTheDocument();
  });

  it('renders Immich shared link alongside the album link', () => {
    const links: ExternalLink[] = [
      {
        source: 'immich_album',
        url: 'https://immich.example.com/albums/album-uuid',
        external_id: 'album-uuid',
      },
      {
        source: 'immich_shared',
        url: 'https://immich.example.com/share/tok',
        external_id: 'album-uuid',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const sharedLink = screen.getByTestId('external-link-immich_shared');
    expect(sharedLink).toHaveAttribute(
      'href',
      'https://immich.example.com/share/tok'
    );
    expect(sharedLink).toHaveAttribute(
      'aria-label',
      'Open in Immich Shared Link'
    );
    expect(screen.getByText('Immich Shared Link')).toBeInTheDocument();
  });

  it('renders Immich person link for a contact', () => {
    const links: ExternalLink[] = [
      {
        source: 'immich',
        url: 'https://immich.example.com/people/person-uuid',
        external_id: 'person-uuid',
      },
    ];

    render(<ExternalLinksDisplay links={links} />);

    const linkElement = screen.getByTestId('external-link-immich');
    expect(linkElement).toHaveAttribute(
      'href',
      'https://immich.example.com/people/person-uuid'
    );
    expect(linkElement).toHaveAttribute('aria-label', 'Open in Immich Photo');
    expect(screen.getByText('Immich Photo')).toBeInTheDocument();
  });
});
