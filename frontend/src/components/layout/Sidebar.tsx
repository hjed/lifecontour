'use client';

/**
 * Sidebar navigation component with hierarchical menu structure.
 *
 * Features collapsible sections for Contacts and Journals with proper
 * icons, active state highlighting, mobile responsiveness, and global
 * state management via SidebarContext.
 *
 * Contact tags render as a nested tree with expand/collapse controls.
 */

import { useState, useCallback, Suspense } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { usePathname, useSearchParams } from 'next/navigation';
import {
  Users,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Star,
  Menu,
  Settings,
  Tag,
  Plus,
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
import { ScrollArea } from '@/components/ui/scroll-area';
import { useSidebar, useSidebarAvailable } from '@/contexts/SidebarContext';
import { useTags } from '@/lib/api/contacts';
import { buildTagTree, TagTreeNode } from '@/lib/tags/buildTagTree';
import { TagContextMenu } from '@/components/contacts/TagContextMenu';
import { CreateTagDialog } from '@/components/contacts/CreateTagDialog';

interface NavigationItem {
  readonly label: string;
  readonly href?: Route;
  readonly icon?: React.ComponentType<{ className?: string }>;
  readonly disabled?: boolean;
}

interface NavigationSection {
  readonly label: string;
  readonly icon: React.ComponentType<{ className?: string }>;
  readonly items: NavigationItem[];
  readonly tagTree?: TagTreeNode[];
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
 * When the contacts page has a `?tag=` param, we do NOT mark the plain
 * "All" link as active — the tag-specific item will be active instead.
 */
function isActiveLink(
  href: Route,
  pathname: string,
  searchParams: URLSearchParams
): boolean {
  if (href === '/contacts') {
    const isOnContacts = pathname === '/contacts' || pathname === '/contacts/';
    // If a tag filter is active, "All" should not be highlighted
    return isOnContacts && !searchParams.has('tag');
  }
  if (href === '/integrations') {
    return pathname === '/integrations' || pathname === '/integrations/';
  }
  return pathname.startsWith(href);
}

// Dynamic navigation configuration
function useNavigationSections(): NavigationSection[] {
  const {
    data: tagsData,
    isLoading: tagsLoading,
    error: tagsError,
  } = useTags();

  const contactItems: NavigationItem[] = [
    { label: 'All', href: '/contacts' as Route },
    { label: 'Favourites', href: '/contacts/favourites' as Route, icon: Star },
  ];

  let tagTree: TagTreeNode[] | undefined;

  // Build tag tree from API data
  if (tagsData?.data && !tagsLoading && !tagsError) {
    tagTree = buildTagTree(tagsData.data);
  } else if (tagsLoading) {
    // Show loading placeholder - no href to disable the link entirely
    contactItems.push({
      label: 'Loading tags...',
      disabled: true,
    });
  }

  return [
    {
      label: 'Contacts',
      icon: Users,
      defaultExpanded: true,
      items: contactItems,
      tagTree,
    },
    {
      label: 'Journals',
      icon: BookOpen,
      defaultExpanded: false,
      items: [{ label: 'All Journals', href: '/journals' as Route }],
    },
    {
      label: 'Integrations',
      icon: Settings,
      defaultExpanded: false,
      items: [{ label: 'Manage', href: '/integrations' as Route }],
    },
  ];
}

/**
 * Recursive component that renders a tag tree node with expand/collapse.
 */
function TagTreeItem({
  node,
  depth,
  expandedTags,
  toggleTag,
  isActiveLink: checkActiveLink,
  onNavigate,
}: {
  readonly node: TagTreeNode;
  readonly depth: number;
  readonly expandedTags: Record<string, boolean>;
  readonly toggleTag: (tagId: string) => void;
  readonly isActiveLink: (href: Route) => boolean;
  readonly onNavigate?: () => void;
}) {
  const hasChildren = node.children.length > 0;
  const tagId = node.tag.id;
  const isExpanded = expandedTags[tagId] ?? false;
  const href = `/contacts?tag=${tagId}` as Route;
  const isActive = checkActiveLink(href);
  const indentSizeRem = 0.75; // matches Tailwind ml-3 visually for nesting

  return (
    <li
      className='list-none'
      style={{ marginLeft: `${depth * indentSizeRem}rem` }}
      data-testid={`tag-tree-item-${node.tag.id}`}
    >
      <TagContextMenu tag={node.tag}>
        <div className='flex items-center'>
          {/* Expand/collapse toggle for branches */}
          {hasChildren ? (
            <Button
              variant='ghost'
              size='sm'
              className='h-6 w-6 shrink-0 p-0'
              onClick={e => {
                e.stopPropagation();
                toggleTag(tagId);
              }}
              aria-expanded={isExpanded}
              aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${node.tag.attributes.name}`}
              data-testid={`tag-toggle-${node.tag.id}`}
            >
              {isExpanded ? (
                <ChevronDown className='h-3 w-3' aria-hidden='true' />
              ) : (
                <ChevronRight className='h-3 w-3' aria-hidden='true' />
              )}
            </Button>
          ) : (
            <span className='inline-block w-6 shrink-0' aria-hidden='true' />
          )}

          {/* Tag link */}
          <Button
            variant='ghost'
            size='sm'
            className={cn(
              'h-auto min-w-0 flex-1 justify-start px-1 py-1.5 font-normal',
              'hover:bg-accent hover:text-accent-foreground',
              'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-2',
              isActive && 'bg-accent text-accent-foreground font-medium'
            )}
            asChild
          >
            <Link
              href={href}
              onClick={onNavigate}
              aria-current={isActive ? 'page' : undefined}
              data-testid={`nav-link-tag-${node.tag.id}`}
            >
              <Tag className='mr-1.5 h-3 w-3 shrink-0' aria-hidden='true' />
              <span className='truncate'>{node.tag.attributes.name}</span>
            </Link>
          </Button>
        </div>
      </TagContextMenu>

      {/* Children (recursive) */}
      {hasChildren && isExpanded && (
        <ul aria-label={`${node.tag.attributes.name} child tags`}>
          {node.children.map(child => (
            <TagTreeItem
              key={child.tag.id}
              node={child}
              depth={depth + 1}
              expandedTags={expandedTags}
              toggleTag={toggleTag}
              isActiveLink={checkActiveLink}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Renders the complete tag tree in the sidebar.
 */
function TagTreeNavigation({
  tree,
  isActiveLink: checkActiveLink,
  onNavigate,
}: {
  readonly tree: TagTreeNode[];
  readonly isActiveLink: (href: Route) => boolean;
  readonly onNavigate?: () => void;
}) {
  const [expandedTags, setExpandedTags] = useState<Record<string, boolean>>({});

  const toggleTag = useCallback((tagId: string) => {
    setExpandedTags(prev => ({
      ...prev,
      [tagId]: !prev[tagId],
    }));
  }, []);

  if (tree.length === 0) {
    return null;
  }

  return (
    <div data-testid='tag-tree-scroll-area'>
      <ul className='m-0 space-y-0.5 p-0' aria-label='Tags'>
        {tree.map(node => (
          <TagTreeItem
            key={node.tag.id}
            node={node}
            depth={0}
            expandedTags={expandedTags}
            toggleTag={toggleTag}
            isActiveLink={checkActiveLink}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
    </div>
  );
}

/**
 * Sidebar content component with context support
 */
function SidebarContentWithContext({ onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { state, toggleSection } = useSidebar();
  const navigationSections = useNavigationSections();

  const checkActiveLink = useCallback(
    (href: Route) => {
      // For tag links (/contacts?tag=X), compare the tag param
      if (typeof href === 'string' && href.startsWith('/contacts?tag=')) {
        const hrefParams = new URLSearchParams(href.split('?')[1]);
        const isOnContacts =
          pathname === '/contacts' || pathname === '/contacts/';
        return (
          isOnContacts && searchParams.get('tag') === hrefParams.get('tag')
        );
      }
      return isActiveLink(href, pathname, searchParams);
    },
    [pathname, searchParams]
  );

  return (
    <SidebarContentInner
      expandedSections={state.expandedSections}
      toggleSection={toggleSection}
      isActiveLink={checkActiveLink}
      onNavigate={onNavigate}
      navigationSections={navigationSections}
    />
  );
}

/**
 * Sidebar content component with local state fallback
 */
function SidebarContentWithLocalState({ onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const navigationSections = useNavigationSections();
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

  const checkActiveLink = useCallback(
    (href: Route) => {
      if (typeof href === 'string' && href.startsWith('/contacts?tag=')) {
        const hrefParams = new URLSearchParams(href.split('?')[1]);
        const isOnContacts =
          pathname === '/contacts' || pathname === '/contacts/';
        return (
          isOnContacts && searchParams.get('tag') === hrefParams.get('tag')
        );
      }
      return isActiveLink(href, pathname, searchParams);
    },
    [pathname, searchParams]
  );

  return (
    <SidebarContentInner
      expandedSections={expandedSections}
      toggleSection={toggleSection}
      isActiveLink={checkActiveLink}
      onNavigate={onNavigate}
      navigationSections={navigationSections}
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
  navigationSections,
}: {
  readonly expandedSections: Record<string, boolean>;
  readonly toggleSection: (sectionLabel: string) => void;
  readonly isActiveLink: (href: Route) => boolean;
  readonly onNavigate?: () => void;
  readonly navigationSections: NavigationSection[];
}) {
  const [showCreateTagDialog, setShowCreateTagDialog] = useState(false);

  return (
    <ScrollArea className='h-full flex-1'>
      <nav
        className='flex flex-col space-y-2 p-4'
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
                  {section.items.map((item, index) => {
                    const isActive =
                      !item.disabled && item.href && isActiveLink(item.href);
                    const ItemIcon = item.icon;
                    const itemKey = item.href || `${section.label}-${index}`;

                    if (item.disabled) {
                      return (
                        <div
                          key={itemKey}
                          className={cn(
                            'h-auto w-full justify-start px-2 py-1.5 font-normal',
                            'text-muted-foreground cursor-not-allowed opacity-50',
                            'flex items-center'
                          )}
                        >
                          {ItemIcon && (
                            <ItemIcon
                              className='mr-2 h-3 w-3'
                              aria-hidden='true'
                            />
                          )}
                          {item.label}
                        </div>
                      );
                    }

                    // Only render as link if href exists
                    if (!item.href) {
                      return (
                        <div
                          key={itemKey}
                          className={cn(
                            'h-auto w-full justify-start px-2 py-1.5 font-normal',
                            'text-muted-foreground',
                            'flex items-center'
                          )}
                        >
                          {ItemIcon && (
                            <ItemIcon
                              className='mr-2 h-3 w-3'
                              aria-hidden='true'
                            />
                          )}
                          {item.label}
                        </div>
                      );
                    }

                    return (
                      <Button
                        key={itemKey}
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
                          href={item.href}
                          onClick={onNavigate}
                          aria-current={isActive ? 'page' : undefined}
                          data-testid={`nav-link-${item.label.toLowerCase()}`}
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

                  {/* Nested tag tree */}
                  {section.tagTree && section.tagTree.length > 0 && (
                    <TagTreeNavigation
                      tree={section.tagTree}
                      isActiveLink={isActiveLink}
                      onNavigate={onNavigate}
                    />
                  )}

                  {/* Create Tag Button */}
                  {section.label === 'Contacts' && (
                    <Button
                      variant='ghost'
                      size='sm'
                      className={cn(
                        'text-muted-foreground h-auto w-full justify-start px-2 py-1.5 font-normal',
                        'hover:bg-accent hover:text-accent-foreground'
                      )}
                      onClick={() => setShowCreateTagDialog(true)}
                    >
                      <Plus className='mr-2 h-3 w-3' aria-hidden='true' />
                      Create Tag
                    </Button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <CreateTagDialog
        open={showCreateTagDialog}
        onOpenChange={setShowCreateTagDialog}
      />
    </ScrollArea>
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
      data-testid='sidebar'
    >
      <div className='flex h-full flex-col'>
        <Suspense fallback={null}>
          <SidebarContent />
        </Suspense>
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
          data-testid='mobile-nav-trigger'
        >
          <Menu className='h-5 w-5' />
        </Button>
      </SheetTrigger>
      <SheetContent side='left' className='w-64 p-0'>
        <SheetHeader className='border-b px-4 py-2'>
          <SheetTitle>Navigation</SheetTitle>
        </SheetHeader>
        <Suspense fallback={null}>
          <SidebarContent onNavigate={() => setOpen(false)} />
        </Suspense>
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
