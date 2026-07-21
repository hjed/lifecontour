import {
  Alert,
  AlertDescription,
  AlertTitle,
} from 'personal-management-frontend';
import { CircleAlert, CircleCheck, Info, RefreshCw } from 'lucide-react';

export function Variants() {
  return (
    <div className='space-y-4'>
      <Alert>
        <Info />
        <AlertTitle>Strava sync finished</AlertTitle>
        <AlertDescription>
          14 activities imported. Two runs still need a journal entry.
        </AlertDescription>
      </Alert>
      <Alert variant='destructive'>
        <CircleAlert />
        <AlertTitle>Could not reach Immich</AlertTitle>
        <AlertDescription>
          The photo sync failed at 6:12 am. Check the integration credentials
          and try again.
        </AlertDescription>
      </Alert>
    </div>
  );
}

export function TitleOnly() {
  return (
    <div className='space-y-4'>
      <Alert>
        <CircleCheck />
        <AlertTitle>Journal entry saved</AlertTitle>
      </Alert>
      <Alert variant='destructive'>
        <CircleAlert />
        <AlertTitle>This contact has no email address</AlertTitle>
      </Alert>
    </div>
  );
}

export function WithoutIcon() {
  return (
    <Alert>
      <AlertTitle>Merge candidates found</AlertTitle>
      <AlertDescription>
        Three contacts look like duplicates of Tom Whitfield. Review them before
        the next Google Contacts sync on 15 July 2026.
      </AlertDescription>
    </Alert>
  );
}

export function LongDescription() {
  return (
    <Alert>
      <RefreshCw />
      <AlertTitle>Backfill in progress</AlertTitle>
      <AlertDescription>
        <p>
          We are rebuilding the search index for 1,284 journal entries. Search
          results may be incomplete until this finishes.
        </p>
        <p>Started 8:30 am · about 4 minutes remaining</p>
      </AlertDescription>
    </Alert>
  );
}
