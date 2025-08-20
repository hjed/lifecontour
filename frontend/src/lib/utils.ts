import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Generates a display name from first and last name
 * @param firstName - The first name
 * @param lastName - The last name
 * @returns A formatted display name
 */
export function generateDisplayName(
  firstName: string,
  lastName: string
): string {
  const trimmedFirst = firstName?.trim() || '';
  const trimmedLast = lastName?.trim() || '';

  if (trimmedFirst && trimmedLast) {
    return `${trimmedFirst} ${trimmedLast}`;
  }

  return trimmedFirst || trimmedLast || '';
}
