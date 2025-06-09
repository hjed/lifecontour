/**
 * Main header component with navigation and global search.
 *
 * Includes responsive navigation, user menu, and global search functionality.
 */

'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Search, Menu, X, User, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '@/lib/auth-context';

export function Header() {
  const { user, isAuthenticated, logout } = useAuth();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const router = useRouter();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/search?q=${encodeURIComponent(searchQuery.trim())}` as any);
    }
  };

  const handleLogout = async () => {
    await logout();
  };

  const navigationItems = [
    { href: '/contacts', label: 'Contacts', testId: 'nav-contacts' },
    { href: '/search', label: 'Search', testId: 'nav-search' },
  ];

  return (
    <header className='bg-background/95 supports-[backdrop-filter]:bg-background/60 border-b backdrop-blur'>
      <div className='container mx-auto px-4'>
        <div className='flex h-16 items-center justify-between'>
          {/* Logo */}
          <div className='flex items-center space-x-4'>
            <Link href='/' className='flex items-center space-x-2'>
              <span className='text-xl font-bold'>Personal CRM</span>
            </Link>
          </div>

          {/* Desktop Navigation */}
          <nav
            className='hidden items-center space-x-6 md:flex'
            data-testid='desktop-navigation'
          >
            {navigationItems.map(item => (
              <Link
                key={item.href}
                href={item.href as any}
                data-testid={item.testId}
                className='hover:text-primary text-sm font-medium transition-colors'
              >
                {item.label}
              </Link>
            ))}
          </nav>

          {/* Global Search */}
          <div className='mx-4 max-w-md flex-1'>
            <form onSubmit={handleSearch} className='relative'>
              <Input
                type='search'
                placeholder='Search contacts, journal, calendar...'
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className='pr-4 pl-10'
                data-testid='global-search-input'
                aria-label='Global search'
              />
              <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
              <Button
                type='submit'
                size='sm'
                className='absolute top-1/2 right-1 h-7 -translate-y-1/2'
                data-testid='global-search-button'
                aria-label='Search'
              >
                <Search className='h-3 w-3' />
              </Button>
            </form>
          </div>

          {/* User Menu / Auth */}
          <div className='flex items-center space-x-4'>
            {isAuthenticated && user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant='ghost'
                    size='sm'
                    className='flex items-center space-x-2'
                    data-testid='user-menu'
                    aria-label='User menu'
                  >
                    <User className='h-4 w-4' />
                    <span data-testid='user-name' className='hidden sm:inline'>
                      {user.name}
                    </span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align='end'>
                  <DropdownMenuItem disabled>
                    <span className='text-muted-foreground text-sm'>
                      {user.email}
                    </span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={handleLogout}
                    data-testid='logout-button'
                  >
                    <LogOut className='mr-2 h-4 w-4' />
                    Logout
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <Button asChild variant='outline' size='sm'>
                <Link href='/auth/login' data-testid='login-button'>
                  Login
                </Link>
              </Button>
            )}

            {/* Mobile Menu Button */}
            <Button
              variant='ghost'
              size='sm'
              className='md:hidden'
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              data-testid='mobile-menu-button'
              aria-label='Toggle mobile menu'
            >
              {isMobileMenuOpen ? (
                <X className='h-5 w-5' />
              ) : (
                <Menu className='h-5 w-5' />
              )}
            </Button>
          </div>
        </div>

        {/* Mobile Navigation */}
        {isMobileMenuOpen && (
          <nav className='border-t py-4 md:hidden' data-testid='mobile-menu'>
            <div className='flex flex-col space-y-2'>
              {navigationItems.map(item => (
                <Link
                  key={item.href}
                  href={item.href as any}
                  data-testid={item.testId}
                  className='hover:text-primary px-2 py-2 text-sm font-medium transition-colors'
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </nav>
        )}
      </div>
    </header>
  );
}
