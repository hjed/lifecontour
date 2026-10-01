import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from 'lifecontour-frontend';
import { CircleAlert, Heart, MapPin, Star } from 'lucide-react';

export function Variants() {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <Badge>Published</Badge>
      <Badge variant='secondary'>Draft</Badge>
      <Badge variant='destructive'>Sync failed</Badge>
      <Badge variant='outline'>Archived</Badge>
    </div>
  );
}

export function JournalTags() {
  const tags = [
    'running',
    'catch-up',
    'work',
    'family',
    'melbourne',
    'reading',
    'climbing',
    'health',
  ];
  return (
    <div className='flex flex-wrap items-center gap-2'>
      {tags.map(tag => (
        <Badge key={tag} variant='secondary'>
          {tag}
        </Badge>
      ))}
    </div>
  );
}

export function WithIcons() {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <Badge>
        <Star />
        Favourite
      </Badge>
      <Badge variant='secondary'>
        <MapPin />
        Fitzroy North
      </Badge>
      <Badge variant='outline'>
        <Heart />
        Mood 8 / 10
      </Badge>
      <Badge variant='destructive'>
        <CircleAlert />
        Immich conflict
      </Badge>
    </div>
  );
}

export function InContext() {
  return (
    <Card className='max-w-sm'>
      <CardHeader>
        <div className='flex items-center justify-between gap-2'>
          <CardTitle>Coffee with Priya</CardTitle>
          <Badge variant='outline'>Event</Badge>
        </div>
        <CardDescription>Monday, 13 July 2026 · 8:45 am</CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-sm'>
          Caught up at Patricia before standup. She&apos;s moving to the
          Melbourne office in September.
        </p>
        <div className='flex flex-wrap gap-2'>
          <Badge variant='secondary'>catch-up</Badge>
          <Badge variant='secondary'>work</Badge>
          <Badge variant='secondary'>coffee</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
