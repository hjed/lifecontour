import { z } from 'zod';

// Common validation schemas
export const emailSchema = z.string().email('Please enter a valid email address');

export const urlSchema = z.string().url('Please enter a valid URL');

export const phoneSchema = z
  .string()
  .regex(
    /^(\+61|0)[2-9]\d{8}$/,
    'Please enter a valid Australian phone number (e.g., +61412345678 or 0412345678)'
  );

export const postcodeSchema = z
  .string()
  .regex(/^\d{4}$/, 'Please enter a valid Australian postcode (4 digits)');

// Date validation schemas
export const dateSchema = z.coerce.date();

export const futureDateSchema = z.coerce
  .date()
  .refine(date => date > new Date(), 'Date must be in the future');

export const pastDateSchema = z.coerce
  .date()
  .refine(date => date < new Date(), 'Date must be in the past');

// Australian date format validation (DD/MM/YYYY)
export const australianDateSchema = z
  .string()
  .regex(
    /^(0[1-9]|[12]\d|3[01])\/(0[1-9]|1[0-2])\/\d{4}$/,
    'Please enter date in DD/MM/YYYY format'
  );

// ID validation schemas
export const idSchema = z.string().min(1, 'ID is required');

export const uuidSchema = z.string().uuid('Please provide a valid UUID');

// Pagination validation schemas
export const paginationSchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(100).default(20),
  cursor: z.string().optional(),
});

// Search validation schemas
export const searchSchema = z.object({
  query: z.string().optional(),
  filters: z.record(z.unknown()).optional(),
  sort: z.string().optional(),
  order: z.enum(['asc', 'desc']).default('asc'),
});

// File validation schemas
export const fileTypeSchema = z.enum([
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/pdf',
  'text/plain',
  'text/csv',
]);

export const fileSizeSchema = z.number().max(10 * 1024 * 1024, 'File size must be less than 10MB'); // 10MB limit

// Contact validation schemas
export const contactNameSchema = z
  .string()
  .min(1, 'Name is required')
  .max(100, 'Name must be less than 100 characters');

export const contactEmailSchema = emailSchema.optional();

export const contactPhoneSchema = phoneSchema.optional();

// Export commonly used composed schemas
export const baseEntitySchema = z.object({
  id: idSchema,
  createdAt: dateSchema,
  updatedAt: dateSchema,
});

export const timestampSchema = z.object({
  createdAt: dateSchema,
  updatedAt: dateSchema,
});
