/**
 * The New dialog's Journal panel: the full journal create form, as on
 * `/journals/new`.
 *
 * `JournalCreateForm` runs the create itself (journal, then any GPX tracks)
 * and hands the new journal's id to `onSuccess`, which replaces its own
 * navigation. The panel then closes the dialog and opens the journal, as the
 * page does, but only while it is still on screen: a create that settles after
 * the dialog was closed has still made the journal, it just does not pull the
 * user to it. The page renders the form directly and is unchanged.
 */

'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import type { Route } from 'next';

import { JournalCreateForm } from '@/components/journals/JournalCreateForm';
import type { NewEntityPanelProps } from '@/components/layout/new-dialog/types';

export function NewJournalPanel({ onCreated, onCancel }: NewEntityPanelProps) {
  const router = useRouter();
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const handleSuccess = (journalId: string) => {
    if (!mounted.current) return;
    onCreated();
    router.push(`/journals/${journalId}` as Route);
  };

  return <JournalCreateForm onSuccess={handleSuccess} onCancel={onCancel} />;
}
