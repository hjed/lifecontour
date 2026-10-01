'use client';

/**
 * User menu component for authenticated users.
 *
 * Displays user information and provides logout functionality.
 */

import { useState } from 'react';
import { Code, LogOut, User, Settings } from 'lucide-react';
import Link from 'next/link';
import type { Route } from 'next';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { useAuth } from '@/lib/auth/AuthProvider';
import { PROJECT_LINKS, SOURCE_CODE_URL, UI_TEXT } from '@/lib/constants';

const PROJECT_LINK_ICONS = {
  [SOURCE_CODE_URL]: Code,
} as const;

export function UserMenu() {
  const { state, logout } = useAuth();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setIsLoggingOut(false);
    }
  };

  if (!state.isAuthenticated || !state.user) {
    return null;
  }

  const user = state.user;
  const initials = user.name
    ? user.name
        .split(' ')
        .map(n => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user.email?.slice(0, 2).toUpperCase() || 'U';

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant='ghost'
          className='relative h-8 w-8 rounded-full'
          data-testid='user-menu'
        >
          <Avatar className='h-8 w-8'>
            <AvatarImage
              src={user.avatar_url || undefined}
              alt={user.name || user.email}
            />
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className='w-56' align='end' forceMount>
        <DropdownMenuLabel className='font-normal'>
          <div className='flex flex-col space-y-1'>
            <p className='text-sm leading-none font-medium'>
              {user.name || 'User'}
            </p>
            <p className='text-muted-foreground text-xs leading-none'>
              {user.email}
            </p>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <User className='mr-2 h-4 w-4' />
          <span>Profile</span>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href={'/settings' as Route} className='w-full cursor-pointer'>
            <Settings className='mr-2 h-4 w-4' />
            <span>Settings</span>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {PROJECT_LINKS.map(({ href, label }) => {
          const Icon = PROJECT_LINK_ICONS[href];
          return (
            <DropdownMenuItem key={href} asChild>
              <a
                href={href}
                target='_blank'
                rel='noopener noreferrer'
                className='w-full cursor-pointer'
              >
                <Icon className='mr-2 h-4 w-4' aria-hidden='true' />
                <span>{label}</span>
                <span className='sr-only'> {UI_TEXT.OPENS_IN_NEW_TAB}</span>
              </a>
            </DropdownMenuItem>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={handleLogout}
          disabled={isLoggingOut}
          className='text-red-600 focus:text-red-600'
        >
          <LogOut className='mr-2 h-4 w-4' />
          <span>{isLoggingOut ? 'Signing out...' : 'Sign Out'}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
