import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Personal Management System',
  description: 'A personal CRM and journal system with AI integration',
  viewport: 'width=device-width, initial-scale=1',
  robots: 'noindex, nofollow', // Private application
};

export default function RootLayout({
  children,
}: {
  readonly children: React.ReactNode;
}) {
  return (
    <html lang='en-AU' suppressHydrationWarning>
      <body className={inter.className}>
        <div className='bg-background min-h-screen font-sans antialiased'>
          {children}
        </div>
      </body>
    </html>
  );
}
