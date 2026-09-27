import type { GearUsageData, GearUsageItem } from '@/types/journals';

function validDate(value?: string | null): string | null | undefined {
  if (!value) return value;
  return Number.isNaN(new Date(value).getTime()) ? undefined : value;
}

/**
 * The gear items a GEAR_USAGE entry lists, dropping a buffer date that does not
 * parse rather than show it as "Invalid Date".
 */
export function gearUsageItems(data?: GearUsageData | null): GearUsageItem[] {
  return (data?.items ?? []).map(item => {
    const cleaned: GearUsageItem = { gear_item_id: item.gear_item_id };
    const checkout = validDate(item.checkout_date);
    const checkin = validDate(item.checkin_date);
    if (checkout !== undefined) cleaned.checkout_date = checkout;
    if (checkin !== undefined) cleaned.checkin_date = checkin;
    return cleaned;
  });
}

/** Why these items cannot be saved, or `null` when they can. */
export function gearUsageItemsError(
  items: readonly GearUsageItem[]
): string | null {
  if (items.length === 0) {
    return 'Gear Usage requires at least one gear item.';
  }
  const inverted = items.some(
    item =>
      item.checkout_date &&
      item.checkin_date &&
      new Date(item.checkin_date) < new Date(item.checkout_date)
  );
  return inverted ? 'Checkin date cannot be before checkout date.' : null;
}
