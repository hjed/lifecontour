import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  LoadingSpinner,
} from 'personal-management-frontend';

export function Sizes() {
  return (
    <div className='flex items-center gap-8'>
      <LoadingSpinner size='sm' />
      <LoadingSpinner size='md' />
      <LoadingSpinner size='lg' />
    </div>
  );
}

export function WithText() {
  return (
    <div className='space-y-6'>
      <LoadingSpinner size='sm' text='Checking Strava…' />
      <LoadingSpinner size='md' text='Loading journal entries…' />
      <LoadingSpinner size='lg' text='Rebuilding search index…' />
    </div>
  );
}

export function InCard() {
  return (
    <Card className='max-w-sm'>
      <CardHeader>
        <CardTitle>Recent contacts</CardTitle>
      </CardHeader>
      <CardContent className='py-8'>
        <LoadingSpinner text='Loading contacts…' />
      </CardContent>
    </Card>
  );
}
