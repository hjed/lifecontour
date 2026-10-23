'use client';

import { AlertCircle, MapPinOff } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  useContactImportIssues,
  useDismissContactImportIssue,
} from '@/lib/api/contact-import-issues';
import { describeAddress, skippedReason } from '@/lib/import-issues';

export interface ContactImportIssuesAlertProps {
  readonly contactId: string;
}

/**
 * The contact's addresses a Google import left out, for review (#1820).
 *
 * The address is still in Google; fixing it there imports it on the next sync
 * and clears this flag. Dismissing hides it while Google keeps it as it is.
 */
export function ContactImportIssuesAlert({
  contactId,
}: ContactImportIssuesAlertProps) {
  const { data, error } = useContactImportIssues(contactId);
  const dismiss = useDismissContactImportIssue();
  const issues = data?.data ?? [];

  // Only when there is nothing to show: a failed refresh keeps the last list.
  if (error && !data) {
    return (
      <Alert variant='destructive'>
        <AlertCircle className='h-4 w-4' />
        <AlertTitle>Couldn’t check for skipped Google addresses</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }

  if (issues.length === 0) {
    return null;
  }

  return (
    <div className='space-y-2' data-testid='contact-import-issues'>
      {issues.map(issue => {
        const { address, reason } = issue.attributes;
        return (
          <Alert key={issue.id}>
            <MapPinOff className='h-4 w-4' />
            <AlertTitle>A Google address wasn’t imported</AlertTitle>
            <AlertDescription>
              <p>
                <span className='font-medium'>{describeAddress(address)}</span>
                {' — '}
                {skippedReason(reason, address)}.
              </p>
              <p>
                Fix it in Google Contacts and it will import on the next sync.
              </p>
              <Button
                variant='outline'
                size='sm'
                className='mt-2'
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate(issue.id)}
              >
                Dismiss
              </Button>
            </AlertDescription>
          </Alert>
        );
      })}
    </div>
  );
}
