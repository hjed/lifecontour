import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from 'lifecontour-frontend';

// Inline data URI so the image path renders without a network request.
const PORTRAIT =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">
      <rect width="80" height="80" fill="#4f6bed"/>
      <circle cx="40" cy="31" r="14" fill="#dbe2ff"/>
      <path d="M12 80c0-16 12.5-26 28-26s28 10 28 26z" fill="#dbe2ff"/>
    </svg>`
  );

export function Fallbacks() {
  const people = [
    'Priya Raman',
    'Tom Whitfield',
    'Sarah Nguyen',
    'Alex Taylor',
  ];
  return (
    <div className='flex flex-wrap items-center gap-3'>
      {people.map(name => (
        <Avatar key={name}>
          <AvatarFallback>
            {name
              .split(' ')
              .map(part => part[0])
              .join('')}
          </AvatarFallback>
        </Avatar>
      ))}
    </div>
  );
}

export function WithImage() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Avatar>
        <AvatarImage src={PORTRAIT} alt='Priya Raman' />
        <AvatarFallback>PR</AvatarFallback>
      </Avatar>
      <Avatar className='h-12 w-12'>
        <AvatarImage src={PORTRAIT} alt='Priya Raman' />
        <AvatarFallback>PR</AvatarFallback>
      </Avatar>
      <Avatar className='h-16 w-16'>
        <AvatarImage src={PORTRAIT} alt='Priya Raman' />
        <AvatarFallback>PR</AvatarFallback>
      </Avatar>
    </div>
  );
}

export function Sizes() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Avatar className='h-6 w-6'>
        <AvatarFallback className='text-xs'>TW</AvatarFallback>
      </Avatar>
      <Avatar className='h-8 w-8'>
        <AvatarFallback className='text-xs'>TW</AvatarFallback>
      </Avatar>
      <Avatar>
        <AvatarFallback>TW</AvatarFallback>
      </Avatar>
      <Avatar className='h-12 w-12'>
        <AvatarFallback>TW</AvatarFallback>
      </Avatar>
      <Avatar className='h-16 w-16'>
        <AvatarFallback className='text-lg'>TW</AvatarFallback>
      </Avatar>
    </div>
  );
}

export function ContactList() {
  const contacts = [
    {
      name: 'Priya Raman',
      initials: 'PR',
      detail: 'Last contacted 13 July 2026',
      tag: 'Colleague',
    },
    {
      name: 'Tom Whitfield',
      initials: 'TW',
      detail: 'Last contacted 2 July 2026',
      tag: 'Climbing',
    },
    {
      name: 'Sarah Nguyen',
      initials: 'SN',
      detail: 'Last contacted 28 June 2026',
      tag: 'Family',
    },
  ];

  return (
    <Card className='max-w-md'>
      <CardHeader>
        <CardTitle>Recent contacts</CardTitle>
      </CardHeader>
      <CardContent className='space-y-4'>
        {contacts.map(contact => (
          <div key={contact.name} className='flex items-center gap-3'>
            <Avatar>
              <AvatarFallback>{contact.initials}</AvatarFallback>
            </Avatar>
            <div className='min-w-0 flex-1'>
              <p className='truncate text-sm font-medium'>{contact.name}</p>
              <p className='text-muted-foreground truncate text-xs'>
                {contact.detail}
              </p>
            </div>
            <Badge variant='secondary'>{contact.tag}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function Stacked() {
  const people = ['PR', 'TW', 'SN', 'AT'];
  return (
    <div className='flex items-center gap-3'>
      <div className='flex items-center'>
        {people.map((initials, index) => (
          <Avatar
            key={initials}
            className='border-2'
            style={{
              borderColor: 'var(--background)',
              marginLeft: index === 0 ? undefined : '-0.75rem',
            }}
          >
            <AvatarFallback className='text-xs'>{initials}</AvatarFallback>
          </Avatar>
        ))}
      </div>
      <span className='text-muted-foreground text-sm'>
        4 people linked to this entry
      </span>
    </div>
  );
}
