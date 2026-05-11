/**
 * External system links display component.
 *
 * Renders a compact list of external system links (Strava, Google Calendar,
 * Google Contacts) with appropriate icons and clickable URLs.
 * Designed for secondary metadata areas on journal and contact detail pages.
 */

'use client';

import { ExternalLink as ExternalLinkIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { ExternalLink } from '@/lib/external-links';
import {
  getExternalLinkIcon,
  getExternalLinkLabel,
} from '@/lib/external-links';
import { cn } from '@/lib/utils';

interface ExternalLinksDisplayProps {
  /** List of external system links to display */
  readonly links: ExternalLink[];
  /** Additional CSS classes */
  readonly className?: string;
}

/**
 * Displays external system links as badges with icons.
 *
 * Each link shows the system icon and name. When a URL is available,
 * the badge is clickable and opens in a new tab. When no URL is
 * constructable, the icon is shown without a link.
 *
 * Renders nothing when there are no links.
 */
export function ExternalLinksDisplay({
  links,
  className,
}: ExternalLinksDisplayProps) {
  if (!links || links.length === 0) {
    return null;
  }

  return (
    <div
      className={cn('space-y-2', className)}
      data-testid='external-links-section'
    >
      <div className='text-sm font-medium'>Linked Systems</div>
      <div className='flex flex-wrap items-center gap-2'>
        {links.map((link, index) => {
          const Icon = getExternalLinkIcon(link.source);
          const label = getExternalLinkLabel(link.source);
          const key = `${link.source}-${link.external_id || index}`;

          if (link.url) {
            return (
              <a
                key={key}
                href={link.url}
                target='_blank'
                rel='noopener noreferrer'
                className='focus-visible:ring-ring rounded-md focus-visible:ring-1 focus-visible:outline-none'
                aria-label={`Open in ${label}`}
                data-testid={`external-link-${link.source}`}
              >
                <Badge
                  variant='outline'
                  className='hover:bg-accent cursor-pointer gap-1.5 text-xs transition-colors'
                >
                  <Icon className='h-3 w-3' aria-hidden='true' />
                  <span>{label}</span>
                  <ExternalLinkIcon
                    className='h-2.5 w-2.5 opacity-50'
                    aria-hidden='true'
                  />
                </Badge>
              </a>
            );
          }

          return (
            <Badge
              key={key}
              variant='outline'
              className='text-muted-foreground gap-1.5 text-xs'
              data-testid={`external-link-${link.source}`}
            >
              <Icon className='h-3 w-3' aria-hidden='true' />
              <span>{label}</span>
            </Badge>
          );
        })}
      </div>
    </div>
  );
}
