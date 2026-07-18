/**
 * TemplatesDoneList — the dashboard's abseil templates done.
 *
 * The unique templates referenced by the user's abseiling-derived activities
 * (the canyons / caves / climbs actually done), grouped by template type, each
 * with a per-template done-count. Templates link to the settings templates
 * section, matching the durable template reference on journal detail
 * (TemplateReference.tsx) — there is no per-template page.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { BookTemplate } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { TYPE_LABELS } from '@/components/journals/JournalTypeBadges';
import { useOutdoorDashboard } from '@/lib/api/outdoor-dashboard';

/** Where a template links to — the settings templates section. */
const TEMPLATES_HREF = '/settings#templates' as Route;

/**
 * A readable label for a template type. Template types overlap the journal
 * type enum for canyoning/caving/climbing, but "abseiling" has no journal-type
 * badge label, so fall back to capitalising the raw value.
 */
function templateTypeLabel(templateType: string): string {
  // Widen to a partial record rather than asserting membership, so the
  // fallback stays reachable for template types outside the journal enum.
  const labels: Partial<Record<string, string>> = TYPE_LABELS;
  return (
    labels[templateType] ??
    templateType.charAt(0).toUpperCase() + templateType.slice(1)
  );
}

export function TemplatesDoneList() {
  const { data, isLoading, error } = useOutdoorDashboard();

  const templatesDone = data?.data.attributes.templates_done ?? {};
  const templateTypes = Object.keys(templatesDone).sort((a, b) =>
    a.localeCompare(b)
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Abseil templates done</CardTitle>
        <CardDescription>
          The canyons, caves and climbs your abseiling activities reference,
          grouped by type, with how many times you have done each.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className='space-y-3' data-testid='templates-done-loading'>
            <Skeleton className='h-12 w-full' />
            <Skeleton className='h-12 w-full' />
          </div>
        )}

        {error && !isLoading && (
          <Alert variant='destructive' data-testid='templates-done-error'>
            <p>Failed to load templates done: {error.message}</p>
          </Alert>
        )}

        {!isLoading && !error && (
          <div data-testid='templates-done-ready'>
            {templateTypes.length === 0 ? (
              <p
                className='text-muted-foreground py-4 text-sm'
                data-testid='templates-done-empty-state'
              >
                No templates done yet — reference a template from an abseiling
                activity to see it here.
              </p>
            ) : (
              <div className='space-y-6'>
                {templateTypes.map(templateType => {
                  const headingId = `templates-done-heading-${templateType}`;
                  const label = templateTypeLabel(templateType);
                  return (
                    <div
                      key={templateType}
                      className='space-y-2'
                      data-testid={`templates-done-group-${templateType}`}
                    >
                      <h4
                        id={headingId}
                        className='text-foreground text-sm font-semibold'
                      >
                        {label}
                      </h4>
                      <ul className='space-y-2' aria-labelledby={headingId}>
                        {templatesDone[templateType].map(template => (
                          <li
                            key={template.template_id}
                            className='flex items-center justify-between gap-3 rounded-lg border p-3'
                            data-testid={`templates-done-item-${template.template_id}`}
                          >
                            <span className='flex min-w-0 items-center gap-2'>
                              <BookTemplate
                                className='text-muted-foreground h-4 w-4 shrink-0'
                                aria-hidden='true'
                              />
                              <Link
                                href={TEMPLATES_HREF}
                                className='text-foreground font-medium underline-offset-4 hover:underline'
                              >
                                {template.name}
                              </Link>
                            </span>
                            <span
                              className='text-muted-foreground shrink-0 text-sm'
                              data-testid={`templates-done-count-${template.template_id}`}
                            >
                              Done {template.done_count}{' '}
                              {template.done_count === 1 ? 'time' : 'times'}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
