'use client';

/**
 * Breadcrumb navigation component for showing current page hierarchy.
 *
 * Automatically generates breadcrumbs based on the current pathname
 * with support for dynamic routes and custom labels.
 */

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { ChevronRight, Home } from 'lucide-react';
import { cn } from '@/lib/utils';

interface BreadcrumbItem {
  label: string;
  href: string;
  isActive?: boolean;
}

interface BreadcrumbProps {
  readonly className?: string;
  readonly customItems?: BreadcrumbItem[];
  readonly showHome?: boolean;
}

/**
 * Route label mappings for better display names
 */
const ROUTE_LABELS: Record<string, string> = {
  contacts: 'Contacts',
  favourites: 'Favourites',
  groups: 'Groups',
  journals: 'Journals',
  new: 'New',
  edit: 'Edit',
};

/**
 * Generate a human-readable label for dynamic route segments.
 *
 * Handles numeric IDs and provides contextual labels based on the parent route.
 *
 * @param segment - The current route segment (e.g., "123", "contacts")
 * @param parentSegment - The previous route segment for context
 * @param segmentIndex - The position of this segment in the path
 * @returns A formatted label for display
 */
function getDynamicRouteLabel(
  segment: string,
  parentSegment: string | undefined,
  segmentIndex: number
): string {
  // Use predefined label if available
  if (ROUTE_LABELS[segment]) {
    return ROUTE_LABELS[segment];
  }

  // Handle numeric IDs with contextual labeling
  if (segment.match(/^\d+$/)) {
    if (parentSegment === 'groups') {
      return `Group ${segment}`;
    } else if (parentSegment === 'contacts' && segmentIndex === 1) {
      return 'Contact Details';
    } else {
      return `#${segment}`;
    }
  }

  // Default to the segment itself
  return segment;
}

/**
 * Generate breadcrumb items from pathname
 */
function generateBreadcrumbs(pathname: string): BreadcrumbItem[] {
  const segments = pathname.split('/').filter(Boolean);
  const breadcrumbs: BreadcrumbItem[] = [];

  let currentPath = '';

  segments.forEach((segment, index) => {
    currentPath += `/${segment}`;
    const isLast = index === segments.length - 1;
    const parentSegment = segments[index - 1];

    // Generate human-readable label using helper function
    const label = getDynamicRouteLabel(segment, parentSegment, index);

    breadcrumbs.push({
      label,
      href: currentPath,
      isActive: isLast,
    });
  });

  return breadcrumbs;
}

export function Breadcrumb({
  className,
  customItems,
  showHome = true,
}: BreadcrumbProps) {
  const pathname = usePathname();

  // Use custom items if provided, otherwise generate from pathname
  const items = customItems || generateBreadcrumbs(pathname);

  // Don't show breadcrumbs on home page
  if (pathname === '/' || items.length === 0) {
    return null;
  }

  return (
    <nav
      className={cn(
        'text-muted-foreground flex items-center space-x-1 text-sm',
        className
      )}
      aria-label='Breadcrumb navigation'
    >
      {showHome && (
        <>
          <Link
            href='/'
            className='hover:text-foreground flex items-center transition-colors'
            aria-label='Go to home page'
          >
            <Home className='h-4 w-4' aria-hidden='true' />
            <span className='sr-only'>Home</span>
          </Link>
          {items.length > 0 && (
            <ChevronRight className='h-4 w-4' aria-hidden='true' />
          )}
        </>
      )}

      <ol className='flex items-center space-x-1'>
        {items.map((item, index) => (
          <li key={item.href} className='flex items-center space-x-1'>
            {index > 0 && (
              <ChevronRight className='h-4 w-4' aria-hidden='true' />
            )}
            {item.isActive ? (
              <span className='text-foreground font-medium' aria-current='page'>
                {item.label}
              </span>
            ) : (
              <Link
                href={item.href as never}
                className='hover:text-foreground transition-colors'
              >
                {item.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * Breadcrumb separator component for custom layouts
 */
export function BreadcrumbSeparator({
  className,
}: {
  readonly className?: string;
}) {
  return (
    <ChevronRight
      className={cn('text-muted-foreground h-4 w-4', className)}
      aria-hidden='true'
    />
  );
}

/**
 * Individual breadcrumb item component for custom layouts
 */
export function BreadcrumbItem({
  children,
  className,
  isActive = false,
}: {
  readonly children: React.ReactNode;
  readonly className?: string;
  readonly isActive?: boolean;
}) {
  return (
    <span
      className={cn(
        'text-sm',
        isActive
          ? 'text-foreground font-medium'
          : 'text-muted-foreground hover:text-foreground transition-colors',
        className
      )}
      aria-current={isActive ? 'page' : undefined}
    >
      {children}
    </span>
  );
}
