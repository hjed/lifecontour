/**
 * Main layout component that wraps all pages.
 * 
 * Includes header with navigation and provides consistent layout structure.
 */

'use client';

import React from 'react';
import { Header } from './header';

interface MainLayoutProps {
  children: React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="container mx-auto px-4 py-8">
        {children}
      </main>
    </div>
  );
}
