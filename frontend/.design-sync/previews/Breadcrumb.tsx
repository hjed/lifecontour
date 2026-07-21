import { Breadcrumb } from 'personal-management-frontend';

/**
 * Derived from the current route. The preview harness pins the pathname to
 * `/journals`, which is what the real app renders under the header.
 */
export function FromPathname() {
  return <Breadcrumb />;
}

/** A detail page supplies its own trail so the record gets a readable label. */
export function ContactDetail() {
  return (
    <Breadcrumb
      customItems={[
        { label: 'Contacts', href: '/contacts' },
        { label: 'Priya Nair', href: '/contacts/318', isActive: true },
      ]}
    />
  );
}

/** Deeper trail, home icon suppressed for pages that already show one. */
export function WithoutHome() {
  return (
    <Breadcrumb
      showHome={false}
      customItems={[
        { label: 'Journals', href: '/journals' },
        { label: 'Outdoor Logbook', href: '/journals/outdoor-logbook' },
        {
          label: 'Cathedral Ranges traverse',
          href: '/journals/outdoor-logbook/912',
          isActive: true,
        },
      ]}
    />
  );
}
