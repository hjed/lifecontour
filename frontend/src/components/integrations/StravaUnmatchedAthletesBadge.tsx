'use client';

import { useState } from 'react';
import { useJournalUnmatchedStravaAthletes, useCreateStravaMapping } from '@/lib/api/integrations';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import { ContactResource } from '@/types/contacts';
import { Activity } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useQueryClient } from '@tanstack/react-query';
import { journalKeys } from '@/lib/api/journals';

interface StravaUnmatchedAthletesBadgeProps {
  readonly journalId: string;
}

export function StravaUnmatchedAthletesBadge({
  journalId,
}: StravaUnmatchedAthletesBadgeProps) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useJournalUnmatchedStravaAthletes(journalId);
  const createMapping = useCreateStravaMapping();

  const [selectedAthlete, setSelectedAthlete] = useState<{
    id: string;
    name: string;
  } | null>(null);

  if (isLoading || !data?.data || data.data.length === 0) {
    return null;
  }

  const handleLinkParticipant = async (contact: ContactResource) => {
    if (!selectedAthlete) return;

    await createMapping.mutateAsync({
      strava_athlete_id: selectedAthlete.id,
      strava_athlete_name: selectedAthlete.name,
      contact_id: Number(contact.id),
    });

    setSelectedAthlete(null);
    // Invalidate the unmatched athletes list
    queryClient.invalidateQueries({
      queryKey: ['integrations', 'strava', 'unmatched', journalId],
    });
    // Invalidate journal details since a participant was likely added
    queryClient.invalidateQueries({
      queryKey: journalKeys.detail(journalId),
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm font-medium text-muted-foreground">Unmatched Strava Athletes</div>
      <div className="flex flex-wrap gap-2">
        {data.data.map((athlete) => (
          <Badge
            key={athlete.id}
            variant="secondary"
            className="flex items-center gap-1.5 cursor-pointer hover:bg-secondary/80"
            onClick={() =>
              setSelectedAthlete({
                id: athlete.attributes.strava_athlete_id,
                name: athlete.attributes.strava_athlete_name,
              })
            }
          >
            <Activity className="h-3 w-3" />
            {athlete.attributes.strava_athlete_name}
            <span className="ml-1 text-xs text-primary underline underline-offset-2">
              Link
            </span>
          </Badge>
        ))}
      </div>

      <Dialog
        open={!!selectedAthlete}
        onOpenChange={(open) => !open && setSelectedAthlete(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Link Strava Athlete</DialogTitle>
            <DialogDescription>
              Select a contact to link with Strava athlete &quot;{selectedAthlete?.name}&quot;.
              This will add the contact to all past and future journals involving this athlete.
            </DialogDescription>
          </DialogHeader>

          <div className="py-4">
            <ContactSearchCombobox
              onSelect={handleLinkParticipant}
              placeholder="Search contacts..."
            />
          </div>

          <div className="flex justify-end">
            <Button
              variant="outline"
              onClick={() => setSelectedAthlete(null)}
            >
              Cancel
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
