import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ListSkeleton,
} from 'lifecontour-frontend';

export function Default() {
  return <ListSkeleton className='max-w-md' />;
}

export function LongList() {
  return <ListSkeleton className='max-w-md' itemCount={7} />;
}

export function InCard() {
  return (
    <Card className='max-w-md'>
      <CardHeader>
        <CardTitle>Recent contacts</CardTitle>
      </CardHeader>
      <CardContent>
        <ListSkeleton itemCount={4} />
      </CardContent>
    </Card>
  );
}
