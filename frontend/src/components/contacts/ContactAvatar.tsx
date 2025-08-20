import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

interface ContactAvatarProps {
  firstName: string;
  lastName?: string;
  imageUrl?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

/**
 * ContactAvatar component displays a contact's profile picture with intelligent fallback to initials.
 *
 * Features:
 * - Displays profile image when available
 * - Falls back to initials generated from first and last name
 * - Supports multiple sizes (sm, md, lg)
 * - Handles edge cases (empty names, special characters)
 * - Full accessibility support
 */
export function ContactAvatar({
  firstName,
  lastName,
  imageUrl,
  size = 'md',
  className,
}: ContactAvatarProps) {
  // Generate initials from names
  const generateInitials = (first: string, last?: string): string => {
    const cleanFirst = first?.trim() || '';
    const cleanLast = last?.trim() || '';

    if (!cleanFirst && !cleanLast) {
      return '?';
    }

    const firstInitial = cleanFirst.charAt(0).toUpperCase();
    const lastInitial = cleanLast.charAt(0).toUpperCase();

    if (cleanFirst && cleanLast) {
      return `${firstInitial}${lastInitial}`;
    }

    return firstInitial || lastInitial;
  };

  // Generate display name for alt text and aria-label
  const generateDisplayName = (first: string, last?: string): string => {
    const cleanFirst = first?.trim() || '';
    const cleanLast = last?.trim() || '';

    if (!cleanFirst && !cleanLast) {
      return 'Contact avatar';
    }

    if (cleanFirst && cleanLast) {
      return `${cleanFirst} ${cleanLast}`;
    }

    return cleanFirst || cleanLast;
  };

  // Size classes mapping
  const sizeClasses = {
    sm: 'h-8 w-8',
    md: 'h-10 w-10',
    lg: 'h-16 w-16',
  };

  const initials = generateInitials(firstName, lastName);
  const displayName = generateDisplayName(firstName, lastName);

  return (
    <Avatar
      className={cn(sizeClasses[size], className)}
      data-testid='contact-avatar'
      role='img'
      aria-label={displayName}
    >
      {imageUrl && <AvatarImage src={imageUrl} alt={displayName} />}
      <AvatarFallback>{initials}</AvatarFallback>
    </Avatar>
  );
}
