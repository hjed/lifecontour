import { Calendar } from 'lifecontour-frontend';
import { enAU } from 'date-fns/locale';

const JULY_2026 = new Date(2026, 6, 1);

export function SingleDate() {
  return (
    <div className='flex flex-col gap-2'>
      <p className='text-sm font-medium'>Entry date</p>
      <Calendar
        mode='single'
        defaultMonth={JULY_2026}
        selected={new Date(2026, 6, 14)}
        locale={enAU}
        className='rounded-md border'
      />
    </div>
  );
}

export function DateRange() {
  return (
    <div className='flex flex-col gap-2'>
      <p className='text-sm font-medium'>Export range — 6 to 19 July 2026</p>
      <Calendar
        mode='range'
        defaultMonth={JULY_2026}
        numberOfMonths={2}
        selected={{ from: new Date(2026, 6, 6), to: new Date(2026, 6, 19) }}
        locale={enAU}
        className='rounded-md border'
      />
    </div>
  );
}

export function MultipleDates() {
  return (
    <div className='flex flex-col gap-2'>
      <p className='text-sm font-medium'>Days with a run logged</p>
      <Calendar
        mode='multiple'
        defaultMonth={JULY_2026}
        selected={[
          new Date(2026, 6, 2),
          new Date(2026, 6, 7),
          new Date(2026, 6, 14),
          new Date(2026, 6, 21),
        ]}
        locale={enAU}
        className='rounded-md border'
      />
    </div>
  );
}

export function WithDropdownsAndDisabled() {
  return (
    <div className='flex flex-col gap-2'>
      <p className='text-sm font-medium'>
        Backdate an entry — future dates unavailable
      </p>
      <Calendar
        mode='single'
        captionLayout='dropdown'
        defaultMonth={JULY_2026}
        startMonth={new Date(2021, 0, 1)}
        endMonth={new Date(2026, 11, 31)}
        selected={new Date(2026, 6, 9)}
        disabled={{ after: new Date(2026, 6, 21) }}
        locale={enAU}
        className='rounded-md border'
      />
    </div>
  );
}
