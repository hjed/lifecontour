/**
 * The collapsed "Archived (n)" part of a contact's methods or addresses card.
 *
 * Archived values are ones the person no longer uses but that are kept for
 * reference, so they stay out of the way until asked for.
 */

'use client';

import { useId, useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';

export interface ArchivedValuesSectionProps {
  /** What the values are, for the accessible name: "contact methods". */
  readonly noun: string;
  /** How many archived values there are; nothing renders for none. */
  readonly count: number;
  /** The archived rows. */
  readonly children: ReactNode;
  readonly 'data-testid'?: string;
}

export function ArchivedValuesSection({
  noun,
  count,
  children,
  'data-testid': testId,
}: ArchivedValuesSectionProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerId = useId();

  if (count === 0) return null;

  const Chevron = isOpen ? ChevronDown : ChevronRight;

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      className='border-border border-t pt-2'
      data-testid={testId}
    >
      <CollapsibleTrigger
        id={triggerId}
        aria-label={`Archived ${noun} (${count})`}
        data-testid={testId ? `${testId}-trigger` : undefined}
        className='text-muted-foreground hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none'
      >
        <Chevron className='h-4 w-4 shrink-0' aria-hidden='true' />
        <span>Archived ({count})</span>
      </CollapsibleTrigger>
      <CollapsibleContent
        role='region'
        aria-labelledby={triggerId}
        className='space-y-2 pt-2'
      >
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}
