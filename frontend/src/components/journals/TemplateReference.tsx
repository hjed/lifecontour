'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { BookTemplate } from 'lucide-react';
import { getTemplate } from '@/lib/api/templates';

interface TemplateReferenceProps {
  /** The consolidated abseiling template reference to display. */
  readonly templateId: string;
}

/**
 * Renders the durable "Based on: <template name>" reference for an
 * abseiling-derived journal, linking to the settings templates section.
 *
 * Renders nothing until the referenced template name is available (or if the
 * template can no longer be resolved).
 */
export function TemplateReference({ templateId }: TemplateReferenceProps) {
  const { data } = useQuery({
    queryKey: ['template', templateId],
    queryFn: () => getTemplate(templateId),
    enabled: !!templateId,
    staleTime: 5 * 60 * 1000,
  });

  const name = data?.data.attributes.name;
  if (!name) {
    return null;
  }

  return (
    <p className='text-muted-foreground flex items-center gap-2 text-sm'>
      <BookTemplate className='h-4 w-4' aria-hidden='true' />
      <Link
        href='/settings#templates'
        className='text-foreground font-medium hover:underline'
        data-testid='journal-template-reference'
      >
        Based on: {name}
      </Link>
    </p>
  );
}
