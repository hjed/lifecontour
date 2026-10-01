import {
  Badge,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
  TableRowHeader,
} from 'lifecontour-frontend';

export function JournalEntries() {
  const entries = [
    {
      date: '14 July 2026',
      title: 'Morning run along the Yarra',
      type: 'Activity',
      tags: ['running', 'health'],
    },
    {
      date: '13 July 2026',
      title: 'Coffee with Priya',
      type: 'Event',
      tags: ['catch-up', 'work'],
    },
    {
      date: '12 July 2026',
      title: 'Weekend planning notes',
      type: 'Note',
      tags: ['planning'],
    },
    {
      date: '11 July 2026',
      title: 'Felt flat after a late night',
      type: 'Mood rating',
      tags: ['sleep'],
    },
  ];

  return (
    <Table>
      <TableCaption>Journal entries logged in the last week</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead className='w-32'>Date</TableHead>
          <TableHead>Entry</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Tags</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(entry => (
          <TableRow key={entry.title}>
            <TableCell className='text-muted-foreground'>
              {entry.date}
            </TableCell>
            <TableCell className='font-medium'>{entry.title}</TableCell>
            <TableCell>
              <Badge variant='outline'>{entry.type}</Badge>
            </TableCell>
            <TableCell>
              <div className='flex flex-wrap gap-1'>
                {entry.tags.map(tag => (
                  <Badge key={tag} variant='secondary'>
                    {tag}
                  </Badge>
                ))}
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ContactsWithRowHeaders() {
  const contacts = [
    {
      name: 'Priya Raman',
      email: 'priya.raman@example.com',
      relationship: 'Colleague',
      lastContacted: '13 July 2026',
    },
    {
      name: 'Tom Whitfield',
      email: 'tom.whitfield@example.com',
      relationship: 'Climbing partner',
      lastContacted: '2 July 2026',
    },
    {
      name: 'Sarah Nguyen',
      email: 'sarah.nguyen@example.com',
      relationship: 'Family',
      lastContacted: '28 June 2026',
    },
  ];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Email</TableHead>
          <TableHead>Relationship</TableHead>
          <TableHead className='text-right'>Last contacted</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {contacts.map(contact => (
          <TableRow key={contact.email}>
            <TableRowHeader>{contact.name}</TableRowHeader>
            <TableCell className='text-muted-foreground'>
              {contact.email}
            </TableCell>
            <TableCell>
              <Badge variant='secondary'>{contact.relationship}</Badge>
            </TableCell>
            <TableCell className='text-muted-foreground text-right'>
              {contact.lastContacted}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ActivityTotals() {
  const activities = [
    { name: 'Morning run', date: '14 July', distance: '8.2 km', time: '42:10' },
    {
      name: 'Ride to work',
      date: '13 July',
      distance: '11.4 km',
      time: '31:05',
    },
    { name: 'Long run', date: '12 July', distance: '18.6 km', time: '1:38:22' },
  ];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Activity</TableHead>
          <TableHead>Date</TableHead>
          <TableHead className='text-right'>Distance</TableHead>
          <TableHead className='text-right'>Moving time</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {activities.map(activity => (
          <TableRow key={activity.name}>
            <TableCell className='font-medium'>{activity.name}</TableCell>
            <TableCell className='text-muted-foreground'>
              {activity.date} 2026
            </TableCell>
            <TableCell className='text-right'>{activity.distance}</TableCell>
            <TableCell className='text-right'>{activity.time}</TableCell>
          </TableRow>
        ))}
      </TableBody>
      <TableFooter>
        <TableRow>
          <TableCell>Week total</TableCell>
          <TableCell />
          <TableCell className='text-right'>38.2 km</TableCell>
          <TableCell className='text-right'>2:51:37</TableCell>
        </TableRow>
      </TableFooter>
    </Table>
  );
}
