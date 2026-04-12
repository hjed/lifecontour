import { AttendeeStatus, ContactEventRole } from '@/types/journals';

describe('Journal Contact Enums', () => {
  it('AttendeeStatus has expected values', () => {
    expect(AttendeeStatus.ATTENDING).toBe('ATTENDING');
    expect(AttendeeStatus.ATTENDED).toBe('ATTENDED');
    expect(AttendeeStatus.MAYBE).toBe('MAYBE');
    expect(AttendeeStatus.NO_REPLY).toBe('NO_REPLY');
    expect(AttendeeStatus.DECLINED).toBe('DECLINED');
  });

  it('ContactEventRole has expected values', () => {
    expect(ContactEventRole.ORGANISER).toBe('ORGANISER');
    expect(ContactEventRole.FACILITATOR_HELPER).toBe('FACILITATOR_HELPER');
  });
});
