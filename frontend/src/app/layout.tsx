import type { Metadata, Viewport } from 'next/types';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from '@/lib/providers';
import { Header, DesktopSidebar } from '@/components/layout';
import { SidebarProvider } from '@/contexts/SidebarContext';
import { Breadcrumb } from '@/components/navigation/Breadcrumb';
import { APP_NAME, APP_TAGLINE } from '@/lib/constants';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s | ${APP_NAME}` },
  description: APP_TAGLINE,
  robots: 'noindex, nofollow', // Self-hosted instances hold personal data
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
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
          <Providers>
            <SidebarProvider>
              <Header />
              <DesktopSidebar />
              <main className='md:pl-64'>
                <div className='container mx-auto px-4 py-6'>
                  <Breadcrumb className='mb-4' />
                  {children}
                </div>
              </main>
            </SidebarProvider>
          </Providers>
        </div>
      </body>
    </html>
  );
}
