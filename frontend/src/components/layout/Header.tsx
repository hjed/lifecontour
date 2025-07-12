'use client';

/**
 * Main header component with home icon and centered search.
 *
 * Features a prominent home icon on the left, centered global search box,
 * and user menu/theme toggle on the right. Navigation links moved to sidebar.
 */

import Link from 'next/link';
import { Home } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { UserMenu } from '@/components/auth/UserMenu';
import { useAuth } from '@/lib/auth/AuthProvider';
import { GlobalSearch } from '@/components/search/GlobalSearch';

export function Header() {
  const { state } = useAuth();

  return (
    <header className='bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-50 w-full border-b backdrop-blur'>
      <div className='container flex h-14 items-center'>
        {/* Home Icon - Prominent on the left */}
        <div className='flex items-center'>
          <Link
            href='/'
            className='hover:text-foreground/80 text-foreground flex items-center space-x-2 transition-colors'
            aria-label='Go to home page'
          >
            <Home className='h-6 w-6' />
            <span className='hidden font-bold sm:inline-block'>
              Home
            </span>
          </Link>
        </div>

        {/* Centered Search - Only show for authenticated users */}
        {state.isAuthenticated && (
          <div className='flex flex-1 justify-center px-4'>
            <GlobalSearch className='w-full max-w-lg' />
          </div>
        )}

        {/* Right side - Theme Toggle and User Menu */}
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
    </header>
  );
}