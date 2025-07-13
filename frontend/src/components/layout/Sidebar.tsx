'use client';

/**
 * Sidebar navigation component with hierarchical menu structure.
 *
 * Features collapsible sections for Contacts and Journals with proper
 * icons, active state highlighting, mobile responsiveness, and global
 * state management via SidebarContext.
 */

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Users,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Star,
  Menu,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { useSidebar, useSidebarAvailable } from '@/contexts/SidebarContext';

interface NavigationItem {
  readonly label: string;
  readonly href: string;
  readonly icon?: React.ComponentType<{ className?: string }>;
}

interface NavigationSection {
  readonly label: string;
  readonly icon: React.ComponentType<{ className?: string }>;
  readonly items: NavigationItem[];
  readonly defaultExpanded?: boolean;
}

interface SidebarProps {
  readonly className?: string;
}

interface SidebarContentProps {
  readonly onNavigate?: () => void;
}

/**
 * Determines if a given href matches the current pathname for active link highlighting.
 *
 * Special handling for the contacts root path to ensure exact matching.
 */
function isActiveLink(href: string, pathname: string): boolean {
  if (href === '/contacts') {
    return pathname === '/contacts' || pathname === '/contacts/';
  }
  return pathname.startsWith(href);
}

// Navigation configuration
const navigationSections: NavigationSection[] = [
  {
    label: 'Contacts',
    icon: Users,
    defaultExpanded: true,
    items: [
      { label: 'All', href: '/contacts' },
      { label: 'Favourites', href: '/contacts/favourites', icon: Star },
      { label: 'Group 1', href: '/contacts/groups/1' },
      { label: 'Group 2', href: '/contacts/groups/2' },
    ],
  },
  {
    label: 'Journals',
    icon: BookOpen,
    defaultExpanded: false,
    items: [{ label: 'Etc', href: '/journals' }],
  },
];

/**
 * Sidebar content component with context support
 */
function SidebarContentWithContext({ onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const { state, toggleSection } = useSidebar();

  const checkActiveLink = (href: string) => isActiveLink(href, pathname);

  return (
    <SidebarContentInner
      expandedSections={state.expandedSections}
      toggleSection={toggleSection}
      isActiveLink={checkActiveLink}
      onNavigate={onNavigate}
    />
  );
}

/**
 * Sidebar content component with local state fallback
 */
function SidebarContentWithLocalState({ onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >(
    navigationSections.reduce(
      (acc, section) => {
        acc[section.label] = section.defaultExpanded ?? false;
        return acc;
      },
      {} as Record<string, boolean>
    )
  );

  const toggleSection = (sectionLabel: string) => {
    setExpandedSections(prev => ({
      ...prev,
      [sectionLabel]: !prev[sectionLabel],
    }));
  };

  const checkActiveLink = (href: string) => isActiveLink(href, pathname);

  return (
    <SidebarContentInner
      expandedSections={expandedSections}
      toggleSection={toggleSection}
      isActiveLink={checkActiveLink}
      onNavigate={onNavigate}
    />
  );
}

/**
 * Sidebar content component that can be used in both desktop and mobile layouts
 */
function SidebarContent({ onNavigate }: SidebarContentProps) {
  const sidebarAvailable = useSidebarAvailable();

  if (sidebarAvailable) {
    return <SidebarContentWithContext onNavigate={onNavigate} />;
  }

  return <SidebarContentWithLocalState onNavigate={onNavigate} />;
}

/**
 * Inner sidebar content component with shared rendering logic
 */
function SidebarContentInner({
  expandedSections,
  toggleSection,
  isActiveLink,
  onNavigate,
}: {
  readonly expandedSections: Record<string, boolean>;
  readonly toggleSection: (sectionLabel: string) => void;
  readonly isActiveLink: (href: string) => boolean;
  readonly onNavigate?: () => void;
}) {
  return (
    <nav
      className='flex h-full flex-col space-y-2 p-4'
      role='navigation'
      aria-label='Main navigation'
    >
      {navigationSections.map((section, sectionIndex) => {
        const isExpanded = expandedSections[section.label];
        const SectionIcon = section.icon;

        return (
          <div key={section.label} className='space-y-1'>
            {sectionIndex > 0 && <Separator className='my-2' />}

            {/* Section Header */}
            <Button
              variant='ghost'
              className={cn(
                'h-auto w-full justify-start px-2 py-1.5 font-medium',
                'hover:bg-accent hover:text-accent-foreground',
                'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2'
              )}
              onClick={() => toggleSection(section.label)}
              aria-expanded={isExpanded}
              aria-controls={`section-${section.label.toLowerCase()}`}
              id={`section-${section.label.toLowerCase()}-header`}
            >
              <SectionIcon className='mr-2 h-4 w-4' aria-hidden='true' />
              <span className='flex-1 text-left'>{section.label}</span>
              {isExpanded ? (
                <ChevronDown className='h-4 w-4' aria-hidden='true' />
              ) : (
                <ChevronRight className='h-4 w-4' aria-hidden='true' />
              )}
            </Button>

            {/* Section Items */}
            {isExpanded && (
              <div
                id={`section-${section.label.toLowerCase()}`}
                className='ml-6 space-y-1'
                role='group'
                aria-labelledby={`section-${section.label.toLowerCase()}-header`}
              >
                {section.items.map(item => {
                  const isActive = isActiveLink(item.href);
                  const ItemIcon = item.icon;

                  return (
                    <Button
                      key={item.href}
                      variant='ghost'
                      size='sm'
                      className={cn(
                        'h-auto w-full justify-start px-2 py-1.5 font-normal',
                        'hover:bg-accent hover:text-accent-foreground',
                        'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2',
                        isActive &&
                          'bg-accent text-accent-foreground font-medium'
                      )}
                      asChild
                    >
                      <Link
                        href={
                          item.href as
                            | '/contacts'
                            | '/contacts/favourites'
                            | '/contacts/groups/1'
                            | '/contacts/groups/2'
                            | '/journals'
                        }
                        onClick={onNavigate}
                        aria-current={isActive ? 'page' : undefined}
                      >
                        {ItemIcon && (
                          <ItemIcon
                            className='mr-2 h-3 w-3'
                            aria-hidden='true'
                          />
                        )}
                        {item.label}
                      </Link>
                    </Button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/**
 * Desktop sidebar component
 */
export function DesktopSidebar({ className }: SidebarProps) {
  return (
    <aside
      className={cn(
        'hidden md:fixed md:top-14 md:bottom-0 md:left-0 md:z-40 md:flex md:w-64 md:flex-col',
        'bg-background border-border border-r',
        className
      )}
      role='complementary'
      aria-label='Desktop navigation sidebar'
    >
      <div className='flex h-full flex-col'>
        <SidebarContent />
      </div>
    </aside>
  );
}

/**
 * Mobile sidebar component using Sheet
 */
export function MobileSidebar({ className }: SidebarProps) {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant='ghost'
          size='sm'
          className={cn('md:hidden', className)}
          aria-label='Open navigation menu'
        >
          <Menu className='h-5 w-5' />
        </Button>
      </SheetTrigger>
      <SheetContent side='left' className='w-64 p-0'>
        <SheetHeader className='border-b px-4 py-2'>
          <SheetTitle>Navigation</SheetTitle>
        </SheetHeader>
        <SidebarContent onNavigate={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}

/**
 * Main Sidebar component that renders both desktop and mobile versions
 */
export function Sidebar({ className }: SidebarProps) {
  return (
    <>
      <DesktopSidebar className={className} />
      <MobileSidebar className={className} />
    </>
  );
}
