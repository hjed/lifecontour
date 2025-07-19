/**
 * FavouriteToggle component for toggling contact favourite status.
 *
 * Provides a star icon button that allows users to add/remove contacts
 * from their favourites list with proper accessibility and loading states.
 */

import { Star } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useToggleContactFavourite } from '@/lib/api/contacts';
import { cn } from '@/lib/utils';

interface FavouriteToggleProps {
  readonly contactId: string;
  readonly isFavourite: boolean;
  readonly contactName: string;
  readonly className?: string;
  readonly size?: 'sm' | 'md' | 'lg';
}

export function FavouriteToggle({
  contactId,
  isFavourite,
  contactName,
  className,
  size = 'md',
}: FavouriteToggleProps) {
  const toggleFavouriteMutation = useToggleContactFavourite();

  const handleToggle = () => {
    toggleFavouriteMutation.mutate(contactId);
  };

  const ariaLabel = isFavourite
    ? `Remove ${contactName} from favourites`
    : `Add ${contactName} to favourites`;

  const iconSizes = {
    sm: 'h-3 w-3',
    md: 'h-4 w-4',
    lg: 'h-5 w-5',
  };

  const buttonSizes = {
    sm: 'sm',
    md: 'sm',
    lg: 'default',
  } as const;

  return (
    <Button
      type='button'
      variant='ghost'
      size={buttonSizes[size]}
      onClick={handleToggle}
      disabled={toggleFavouriteMutation.isPending}
      aria-label={ariaLabel}
      className={cn(
        'hover:bg-yellow-50 hover:text-yellow-600 focus-visible:ring-yellow-500',
        className
      )}
    >
      <Star
        className={cn(
          iconSizes[size],
          'transition-colors',
          isFavourite
            ? 'fill-yellow-400 text-yellow-400'
            : 'text-gray-400 hover:text-yellow-400'
        )}
        aria-hidden='true'
      />
      <span className='sr-only'>{ariaLabel}</span>
    </Button>
  );
}
