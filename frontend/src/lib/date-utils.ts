/**
 * Date utility functions for the application.
 *
 * Provides consistent date formatting and manipulation across the app,
 * with proper timezone handling and Australian locale support.
 */

import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';

/**
 * Format a Date object as YYYY-MM-DD in local timezone.
 *
 * This avoids timezone issues that occur when using toISOString(),
 * which converts to UTC and can shift the date for users outside UTC.
 *
 * @param date - The date to format
 * @returns Date string in YYYY-MM-DD format
 *
 * @example
 * formatDateOnly(new Date(2024, 0, 15)) // "2024-01-15"
 */
export function formatDateOnly(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Format a date range for display with smart formatting.
 *
 * - Same day: "15 Jan 2024"
 * - Same month: "15 - 20 Jan 2024"
 * - Different months: "15 Jan 2024 - 20 Feb 2024"
 *
 * @param start - Start date (ISO string or Date)
 * @param end - End date (ISO string or Date)
 * @returns Formatted date range string
 *
 * @example
 * formatDateRange("2024-01-15", "2024-01-15") // "15 Jan 2024"
 * formatDateRange("2024-01-15", "2024-01-20") // "15 - 20 Jan 2024"
 * formatDateRange("2024-01-15", "2024-02-20") // "15 Jan 2024 - 20 Feb 2024"
 */
export function formatDateRange(
  start: string | Date,
  end: string | Date
): string {
  const startDate = typeof start === 'string' ? new Date(start) : start;
  const endDate = typeof end === 'string' ? new Date(end) : end;

  // If same day, show single date
  if (format(startDate, 'yyyy-MM-dd') === format(endDate, 'yyyy-MM-dd')) {
    return format(startDate, 'd MMM yyyy', { locale: enAU });
  }

  // If same month and year, show abbreviated format
  if (format(startDate, 'yyyy-MM') === format(endDate, 'yyyy-MM')) {
    return `${format(startDate, 'd', { locale: enAU })} - ${format(endDate, 'd MMM yyyy', { locale: enAU })}`;
  }

  // Different months, show full range
  return `${format(startDate, 'd MMM yyyy', { locale: enAU })} - ${format(endDate, 'd MMM yyyy', { locale: enAU })}`;
}
