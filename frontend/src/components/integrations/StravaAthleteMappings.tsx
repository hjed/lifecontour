'use client';

import { useStravaMappings, useDeleteStravaMapping } from '@/lib/api/integrations';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export function StravaAthleteMappings() {
  const { data, isLoading } = useStravaMappings();
  const deleteMapping = useDeleteStravaMapping();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  const mappings = data?.data || [];

  if (mappings.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground border rounded-md">
        <p>No Strava athlete mappings found.</p>
        <p className="text-sm mt-2">
          Mappings are created automatically when unmatched athletes are linked from a journal.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Strava Athlete Name</TableHead>
            <TableHead>Strava Athlete ID</TableHead>
            <TableHead>Linked Contact ID</TableHead>
            <TableHead className="w-[100px] text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {mappings.map((mapping) => (
            <TableRow key={mapping.id}>
              <TableCell className="font-medium">
                {mapping.attributes.strava_athlete_name}
              </TableCell>
              <TableCell className="text-muted-foreground font-mono text-sm">
                {mapping.attributes.strava_athlete_id}
              </TableCell>
              <TableCell>
                {mapping.attributes.contact_id}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => deleteMapping.mutateAsync(mapping.attributes.strava_athlete_id)}
                  disabled={deleteMapping.isPending}
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  aria-label="Delete mapping"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
