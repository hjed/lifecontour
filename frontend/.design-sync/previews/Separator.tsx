import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Separator,
} from 'lifecontour-frontend';

export function InCard() {
  return (
    <Card className='max-w-sm'>
      <CardHeader>
        <CardTitle>Morning run</CardTitle>
        <CardDescription>Tuesday, 14 July 2026 · 6:15 am</CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <p className='text-sm'>
          8.2 km along the Yarra before work. Cold start, but the last two
          kilometres felt easy.
        </p>
        <Separator />
        <div className='space-y-1'>
          <p className='text-muted-foreground text-xs'>Gear</p>
          <p className='text-sm'>Saucony Endorphin Speed · 412 km logged</p>
        </div>
        <Separator />
        <div className='flex flex-wrap gap-2'>
          <Badge variant='secondary'>running</Badge>
          <Badge variant='secondary'>health</Badge>
        </div>
      </CardContent>
    </Card>
  );
}

export function VerticalInline() {
  return (
    <div className='flex h-5 items-center gap-3 text-sm'>
      <span>8.2 km</span>
      <Separator orientation='vertical' />
      <span>42:10</span>
      <Separator orientation='vertical' />
      <span>5:08 /km</span>
      <Separator orientation='vertical' />
      <span className='text-muted-foreground'>14 July 2026</span>
    </div>
  );
}

export function SectionDivider() {
  const sections = [
    {
      heading: 'Today',
      items: ['Morning run along the Yarra', 'Standup notes'],
    },
    {
      heading: 'Yesterday',
      items: ['Coffee with Priya', 'Bouldering at Northside'],
    },
    {
      heading: 'Sunday, 12 July 2026',
      items: ['Long run', 'Weekend planning notes'],
    },
  ];

  return (
    <div className='max-w-md space-y-4'>
      {sections.map((section, index) => (
        <div key={section.heading} className='space-y-4'>
          {index > 0 && <Separator />}
          <div className='space-y-1'>
            <p className='text-muted-foreground text-xs font-medium uppercase'>
              {section.heading}
            </p>
            {section.items.map(item => (
              <p key={item} className='text-sm'>
                {item}
              </p>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
