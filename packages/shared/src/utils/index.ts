import { format, parseISO } from 'date-fns';
import { enAU } from 'date-fns/locale';
import type { Result, Success, Failure } from '../types/index.js';

// Australian date formatting utilities
export const formatDateAustralian = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'dd/MM/yyyy', { locale: enAU });
};

export const formatDateTimeAustralian = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'dd/MM/yyyy HH:mm', { locale: enAU });
};

export const formatTimeAustralian = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'HH:mm', { locale: enAU });
};

// Currency formatting for Australian locale
export const formatCurrencyAustralian = (amount: number): string => {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
  }).format(amount);
};

// Number formatting for Australian locale
export const formatNumberAustralian = (number: number): string => {
  return new Intl.NumberFormat('en-AU').format(number);
};

// Result pattern utilities
export const success = <T>(data: T): Success<T> => ({
  success: true,
  data,
});

export const failure = (
  error: string,
  code?: string,
  details?: Record<string, unknown>
): Failure => ({
  success: false,
  error,
  code: code ?? 'UNKNOWN_ERROR',
  details: details ?? {},
});

export const isSuccess = <T>(result: Result<T>): result is Success<T> => result.success;
export const isFailure = <T>(result: Result<T>): result is Failure => !result.success;
