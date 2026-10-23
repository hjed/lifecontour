'use client';

import Link from 'next/link';
import { MapPinOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  useContactImportIssues,
  useDismissContactImportIssue,
} from '@/lib/api/contact-import-issues';
import { describeAddress, skippedReason } from '@/lib/import-issues';

/**
 * Every address a Google import left out, across contacts (#1820).
 *
 * Hidden when there are none. Each links to its contact; fixing the address
 * in Google Contacts imports it on the next sync and clears it from here.
 */
export function SkippedAddressesCard() {
  const { data } = useContactImportIssues();
  const dismiss = useDismissContactImportIssue();
  const issues = data?.data ?? [];

  if (issues.length === 0) {
    return null;
  }

  return (
    <Card data-testid='skipped-addresses'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <MapPinOff className='h-5 w-5' />
          Skipped addresses
        </CardTitle>
        <CardDescription>
          Addresses a Google import couldn’t place. Fix them in Google Contacts
          and they import on the next sync, or dismiss them.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className='divide-y'>
          {issues.map(issue => {
            const { address, reason, contact_id, contact_name } =
              issue.attributes;
            return (
              <li
                key={issue.id}
                className='flex flex-wrap items-start justify-between gap-2 py-3'
              >
                <div className='min-w-0'>
                  <Link
                    href={`/contacts/${contact_id}`}
                    className='font-medium hover:underline'
                  >
                    {contact_name}
                  </Link>
                  <p className='text-sm wrap-anywhere'>
                    {describeAddress(address)}
                  </p>
                  <p className='text-muted-foreground text-sm'>
                    {skippedReason(reason, address)}
                  </p>
                </div>
                <Button
                  variant='outline'
                  size='sm'
                  aria-label={`Dismiss skipped address for ${contact_name}`}
                  disabled={dismiss.isPending}
                  onClick={() => dismiss.mutate(issue.id)}
                >
                  Dismiss
                </Button>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
