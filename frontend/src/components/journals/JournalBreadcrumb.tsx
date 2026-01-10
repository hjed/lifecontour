/**
 * JournalBreadcrumb component for navigating parent hierarchy.
 *
 * Displays a breadcrumb trail showing the parent journal hierarchy
 * with clickable links to navigate up the hierarchy.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { ChevronRight, Home } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ParentJournalSummary } from '@/types/journals';

interface JournalBreadcrumbProps {
  readonly parent?: ParentJournalSummary | null;
  readonly currentTitle: string;
  readonly className?: string;
}

/**
 * Breadcrumb component for journal parent navigation.
 * Displays: Home > Parent Title > Current Title
 */
export function JournalBreadcrumb({
  parent,
  currentTitle,
  className,
}: JournalBreadcrumbProps) {
  return (
    <nav
      aria-label='Breadcrumb'
      className={cn('flex items-center gap-2 text-sm', className)}
      data-testid='journal-breadcrumb'
    >
      {/* Home Link */}
      <Link
        href={'/journals' as Route}
        className='text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors'
        aria-label='Go to journals home'
      >
        <Home className='h-4 w-4' />
        <span>Journals</span>
      </Link>

      {/* Parent Link (if exists) */}
      {parent && (
        <>
          <ChevronRight
            className='text-muted-foreground h-4 w-4'
            aria-hidden='true'
          />
          <Link
            href={`/journals/${parent.id}` as Route}
            className='text-muted-foreground hover:text-foreground transition-colors'
            data-testid='parent-link'
          >
            {parent.title}
          </Link>
        </>
      )}

      {/* Current Journal */}
      <ChevronRight
        className='text-muted-foreground h-4 w-4'
        aria-hidden='true'
      />
      <span
        className='text-foreground font-medium'
        aria-current='page'
        data-testid='current-title'
      >
        {currentTitle}
      </span>
    </nav>
  );
}
