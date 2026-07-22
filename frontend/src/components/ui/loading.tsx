'use client';

/**
 * Loading components for consistent loading states across the application.
 *
 * Provides various loading indicators and skeleton components for
 * different use cases and layouts.
 */

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { Loader2 } from 'lucide-react';

interface LoadingSpinnerProps {
  readonly className?: string;
  readonly size?: 'sm' | 'md' | 'lg';
  readonly text?: string;
}

/**
 * Loading spinner component with optional text
 */
export function LoadingSpinner({
  className,
  size = 'md',
  text,
}: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
  };

  return (
    <div
      className={cn('flex items-center justify-center space-x-2', className)}
    >
      <Loader2
        className={cn('text-muted-foreground animate-spin', sizeClasses[size])}
        aria-hidden='true'
        data-testid='loading-spinner'
      />
      {text && <span className='text-muted-foreground text-sm'>{text}</span>}
      <span className='sr-only'>Loading...</span>
    </div>
  );
}

interface PageLoadingProps {
  readonly className?: string;
  readonly text?: string;
}

/**
 * Full page loading component
 */
export function PageLoading({
  className,
  text = 'Loading...',
}: PageLoadingProps) {
  return (
    <div
      className={cn(
        'flex min-h-[400px] items-center justify-center',
        className
      )}
    >
      <LoadingSpinner size='lg' text={text} />
    </div>
  );
}

interface SkeletonProps {
  readonly className?: string;
}

/**
 * Card skeleton for loading contact cards
 */
export function CardSkeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn('space-y-3 rounded-lg border p-4', className)}
      aria-hidden='true'
    >
      <div className='space-y-2'>
        <Skeleton className='h-4 w-3/4' />
        <Skeleton className='h-3 w-1/2' />
      </div>
      <div className='space-y-1'>
        <Skeleton className='h-3 w-full' />
        <Skeleton className='h-3 w-2/3' />
      </div>
    </div>
  );
}

/**
 * List skeleton for loading lists
 */
export function ListSkeleton({
  className,
  itemCount = 3,
}: SkeletonProps & { readonly itemCount?: number }) {
  return (
    <div className={cn('space-y-2', className)} aria-hidden='true'>
      {Array.from({ length: itemCount }).map((_, index) => (
        <div
          key={`list-skeleton-item-${index}`}
          className='flex items-center space-x-3 p-2'
        >
          <Skeleton className='h-10 w-10 rounded-full' />
          <div className='flex-1 space-y-1'>
            <Skeleton className='h-4 w-3/4' />
            <Skeleton className='h-3 w-1/2' />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Table skeleton for loading tables
 */
export function TableSkeleton({
  className,
  rows = 5,
  columns = 4,
}: SkeletonProps & {
  readonly rows?: number;
  readonly columns?: number;
}) {
  return (
    <div className={cn('space-y-2', className)} aria-hidden='true'>
      {/* Header */}
      <div className='flex space-x-2 border-b pb-2'>
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton
            key={`table-skeleton-header-${index}`}
            className='h-4 flex-1'
          />
        ))}
      </div>

      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={`table-skeleton-row-${rowIndex}`} className='flex space-x-2'>
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={`table-skeleton-cell-${rowIndex}-${colIndex}`}
              className='h-4 flex-1'
            />
          ))}
        </div>
      ))}
    </div>
  );
}

interface LoadingOverlayProps {
  readonly isLoading: boolean;
  readonly children: React.ReactNode;
  readonly className?: string;
  readonly text?: string;
}

/**
 * Loading overlay component that shows loading state over content
 */
export function LoadingOverlay({
  isLoading,
  children,
  className,
  text = 'Loading...',
}: LoadingOverlayProps) {
  return (
    <div className={cn('relative', className)}>
      {children}
      {isLoading && (
        <div className='bg-background/80 absolute inset-0 z-50 flex items-center justify-center backdrop-blur-sm'>
          <LoadingSpinner size='lg' text={text} />
        </div>
      )}
    </div>
  );
}

/**
 * Button loading state component
 */
export function ButtonLoading({
  className,
  text = 'Loading...',
}: {
  readonly className?: string;
  readonly text?: string;
}) {
  return (
    <div className={cn('flex items-center space-x-2', className)}>
      <Loader2 className='h-4 w-4 animate-spin' aria-hidden='true' />
      <span>{text}</span>
    </div>
  );
}
