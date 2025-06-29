'use client';

/**
 * Main header component with navigation and user menu.
 *
 * Displays the site title, navigation links, and user menu for authenticated users.
 */

import Link from 'next/link';
import { Home, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { UserMenu } from '@/components/auth/UserMenu';
import { useAuth } from '@/lib/auth/AuthProvider';

export function Header() {
  const { state } = useAuth();

  return (
    <header className='bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50 w-full border-b backdrop-blur'>
      <div className='container flex h-14 items-center'>
        {/* Logo/Title */}
        <div className='mr-4 hidden md:flex'>
          <Link href='/' className='mr-6 flex items-center space-x-2'>
            <span className='hidden font-bold sm:inline-block'>
              Personal Management System
            </span>
          </Link>
        </div>

        {/* Navigation - only show for authenticated users */}
        {state.isAuthenticated && (
          <nav className='flex items-center space-x-6 text-sm font-medium'>
            <Link
              href='/'
              className='hover:text-foreground/80 text-foreground/60 transition-colors'
            >
              <Home className='h-4 w-4 md:mr-2 md:inline' />
              <span className='hidden md:inline'>Home</span>
            </Link>
            <Link
              href='/contacts'
              className='hover:text-foreground/80 text-foreground/60 transition-colors'
            >
              <Users className='h-4 w-4 md:mr-2 md:inline' />
              <span className='hidden md:inline'>Contacts</span>
            </Link>
          </nav>
        )}

        {/* Spacer */}
        <div className='flex flex-1 items-center justify-between space-x-2 md:justify-end'>
          <div className='w-full flex-1 md:w-auto md:flex-none'>
            {/* Search could go here */}
          </div>

          {/* User Menu */}
          {state.isAuthenticated ? (
            <UserMenu />
          ) : (
            <Button asChild variant='ghost'>
              <Link href='/auth/login'>Sign In</Link>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
