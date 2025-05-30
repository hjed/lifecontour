import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import type { ReactNode } from 'react';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Personal Management System',
  description: 'Personal CRM & Journal System with MCP protocol support',
  authors: [{ name: 'Personal Management System' }],
  robots: 'noindex, nofollow', // Private application
};

export const viewport = {
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang='en-AU' suppressHydrationWarning>
      <body className={inter.className}>
        <div id='root'>{children}</div>
      </body>
    </html>
  );
}
