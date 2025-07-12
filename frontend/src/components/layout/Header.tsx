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

          {/* Theme Toggle and User Menu */}
          <div className='flex items-center space-x-2'>
            <button
              className='border-input bg-background hover:bg-accent hover:text-accent-foreground inline-flex h-8 w-8 items-center justify-center rounded-md border px-0'
              onClick={() => {
                const html = document.documentElement;
                if (html.classList.contains('dark')) {
                  html.classList.remove('dark');
                  localStorage.setItem('theme', 'light');
                } else {
                  html.classList.add('dark');
                  localStorage.setItem('theme', 'dark');
                }
              }}
              aria-label='Toggle theme'
              data-testid='theme-toggle'
            >
              <svg
                className='h-[1.2rem] w-[1.2rem] scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90'
                fill='none'
                height='24'
                stroke='currentColor'
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth='2'
                viewBox='0 0 24 24'
                width='24'
              >
                <circle cx='12' cy='12' r='5' />
                <path d='M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42' />
              </svg>
              <svg
                className='absolute h-[1.2rem] w-[1.2rem] scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0'
                fill='none'
                height='24'
                stroke='currentColor'
                strokeLinecap='round'
                strokeLinejoin='round'
                strokeWidth='2'
                viewBox='0 0 24 24'
                width='24'
              >
                <path d='M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z' />
              </svg>
              <span className='sr-only'>Toggle theme</span>
            </button>
            {state.isAuthenticated ? (
              <UserMenu />
            ) : (
              <Button asChild variant='ghost'>
                <Link href='/auth/login'>Sign In</Link>
              </Button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
