/**
 * The upcoming-dates section's wording rules (**W31**, **W32**).
 *
 * Pure functions, asserted without rendering anything: the badge's wording
 * carries two product rules — a custom date is shown under the name its owner
 * gave it, and a derived age is shown only where the stored precision produced
 * one — and both are far cheaper to pin here than through a row.
 */

import { ImportantDateTypeEnum } from '@/types/contacts';
import {
  dateBadgeLabel,
  dateTypeBadgeClassName,
  dateTypeLabel,
  daysAwayLabel,
  showAllLabel,
} from '@/lib/upcoming-dates-display';

describe('dateTypeLabel', () => {
  it.each([
    [ImportantDateTypeEnum.BIRTHDAY, 'Birthday'],
    [ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE, 'Marriage anniversary'],
    [ImportantDateTypeEnum.ANNIVERSARY_WORK, 'Work anniversary'],
    [ImportantDateTypeEnum.FIRST_MET, 'First met'],
  ])('names %s in full', (dateType, expected) => {
    expect(dateTypeLabel(dateType, null)).toBe(expected);
  });

  // The two anniversaries are why the labels are written out rather than both
  // shortened to "Anniversary": this section shows several contacts at once,
  // and a badge that could mean either says nothing.
  it('keeps the two anniversary types apart', () => {
    expect(
      dateTypeLabel(ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE, null)
    ).not.toBe(dateTypeLabel(ImportantDateTypeEnum.ANNIVERSARY_WORK, null));
  });

  it('shows a custom date under the name its owner gave it', () => {
    expect(dateTypeLabel(ImportantDateTypeEnum.CUSTOM, 'Sobriety')).toBe(
      'Sobriety'
    );
  });

  // "Custom" is the database's word, not the user's, and it tells the person
  // reading the row nothing at all about their own date.
  it('never shows the word "custom" when the name is missing', () => {
    expect(dateTypeLabel(ImportantDateTypeEnum.CUSTOM, null)).toBe(
      'Important date'
    );
  });

  // The value crosses the wire, so a type this build has never heard of is a
  // payload the card still has to draw — legibly, and without blanking.
  it('humanises a type it does not know', () => {
    expect(dateTypeLabel('graduation_day', null)).toBe('Graduation day');
  });
});

describe('dateBadgeLabel', () => {
  it('counts a birthday as an age', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.BIRTHDAY,
        custom_date_type_name: null,
        years: 35,
      })
    ).toBe('Birthday · turns 35');
  });

  it('counts every other type in years', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE,
        custom_date_type_name: null,
        years: 34,
      })
    ).toBe('Marriage anniversary · 34 years');
  });

  it('writes a single year in the singular', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.FIRST_MET,
        custom_date_type_name: null,
        years: 1,
      })
    ).toBe('First met · 1 year');
  });

  // Zero is a real count — a first birthday — and the payload says so
  // explicitly. A truthiness check here would silently drop it.
  it('shows a zeroth year rather than treating it as absent', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.BIRTHDAY,
        custom_date_type_name: null,
        years: 0,
      })
    ).toBe('Birthday · turns 0');
  });

  it('degrades to the bare type when the precision yielded no years', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.BIRTHDAY,
        custom_date_type_name: null,
        years: null,
      })
    ).toBe('Birthday');
  });

  it('counts a custom date under its own name', () => {
    expect(
      dateBadgeLabel({
        date_type: ImportantDateTypeEnum.CUSTOM,
        custom_date_type_name: 'Sobriety',
        years: 3,
      })
    ).toBe('Sobriety · 3 years');
  });
});

describe('dateTypeBadgeClassName', () => {
  it('gives each type its own colour', () => {
    const classNames = Object.values(ImportantDateTypeEnum).map(
      dateTypeBadgeClassName
    );

    expect(new Set(classNames).size).toBe(classNames.length);
  });

  // Fixed rather than derived: the same type must be the same colour on every
  // render, and across the several rows a week routinely holds.
  it('answers the same for a type every time', () => {
    expect(dateTypeBadgeClassName(ImportantDateTypeEnum.BIRTHDAY)).toBe(
      dateTypeBadgeClassName(ImportantDateTypeEnum.BIRTHDAY)
    );
  });

  it('still colours a type it does not know', () => {
    expect(dateTypeBadgeClassName('graduation_day')).toBeTruthy();
  });
});

describe('daysAwayLabel', () => {
  it.each([
    [0, 'Today'],
    [1, 'Tomorrow'],
    [2, 'in 2 days'],
    [6, 'in 6 days'],
  ])('reads %i as %s', (daysAway, expected) => {
    expect(daysAwayLabel(daysAway)).toBe(expected);
  });
});

describe('showAllLabel', () => {
  it('names the whole window rather than what is hidden', () => {
    expect(showAllLabel(5)).toBe('Show all 5 this week');
  });
});
