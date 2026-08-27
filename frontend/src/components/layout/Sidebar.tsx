'use client';

/**
 * Sidebar navigation component with hierarchical menu structure.
 *
 * Features collapsible sections for Contacts and Journals with proper
 * icons, active state highlighting, mobile responsiveness, and global
 * state management via SidebarContext.
 *
 * Contact and journal tags each render as a nested tree with expand/collapse
 * controls, scoped to their own list route.
 */

import { useState, useCallback, Suspense, type ReactNode } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { usePathname, useSearchParams } from 'next/navigation';
import {
  Users,
  BookOpen,
  Home,
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
import { useJournalTags } from '@/lib/api/journals';
import {
  buildTagTree,
  contactTagView,
  journalTagView,
  type TagTreeAdapter,
  type TagTreeNode,
} from '@/lib/tags/buildTagTree';
import type { TagFilterBasePath } from '@/hooks/useTagFilter';
import type { JournalTag } from '@/types/journals';
import { TagContextMenu } from '@/components/contacts/TagContextMenu';
import { CreateTagDialog } from '@/components/contacts/CreateTagDialog';
import { JournalTagContextMenu } from '@/components/journals/JournalTagContextMenu';
import { JournalCreateTagDialog } from '@/components/journals/JournalCreateTagDialog';

interface NavigationItem {
  readonly label: string;
  readonly href?: Route;
  readonly icon?: React.ComponentType<{ className?: string }>;
  readonly disabled?: boolean;
}

/** Props a section's tag tree needs from the rendering sidebar shell. */
interface TagTreeRenderProps {
  readonly isActiveLink: (href: Route) => boolean;
  readonly onNavigate?: () => void;
}

interface NavigationSection {
  readonly label: string;
  readonly icon: React.ComponentType<{ className?: string }>;
  readonly items: NavigationItem[];
  /**
   * Renders the section's tag tree. A callback rather than a `TagTreeNode[]`
   * because each namespace carries a different tag resource shape, and the
   * shell has no business knowing which.
   */
  readonly renderTagTree?: (props: TagTreeRenderProps) => ReactNode;
  /**
   * Renders the section's create-tag dialog. Present only for sections whose
   * namespace supports tag management; the button and its open state are owned
   * by {@link CreateTagAffordance} so each section is independent.
   */
  readonly renderCreateTagDialog?: (props: CreateTagDialogProps) => ReactNode;
  /** Test id of the section's create-tag button. */
  readonly createTagTestId?: string;
  readonly defaultExpanded?: boolean;
}

/** Props the shell passes to a section's create-tag dialog. */
interface CreateTagDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

interface SidebarProps {
  readonly className?: string;
}

interface SidebarContentProps {
  readonly onNavigate?: () => void;
}

/** Matches a sidebar tag link, e.g. `/journals?tag=<id>`. */
const TAG_LINK_PATTERN = /^(\/contacts|\/journals)\?tag=(.+)$/;

/**
 * Determines if a given href matches the current pathname for active link highlighting.
 *
 * The tag-filterable list roots (`/contacts`, `/journals`) match exactly rather
 * than by prefix: when a `?tag=` param is present the plain "All" link is NOT
 * active — the tag-specific item is instead.
 */
function isActiveLink(
  href: Route,
  pathname: string,
  searchParams: URLSearchParams
): boolean {
  if (href === '/contacts' || href === '/journals') {
    const isOnList = pathname === href || pathname === `${href}/`;
    // If a tag filter is active, "All" should not be highlighted
    return isOnList && !searchParams.has('tag');
  }
  if (href === '/integrations') {
    return pathname === '/integrations' || pathname === '/integrations/';
  }
  // The home dashboard matches exactly, and it is the one entry that *must*:
  // every path starts with '/', so the prefix rule below would light Home up
  // on every page in the app.
  if (href === '/') {
    return pathname === '/';
  }
  return pathname.startsWith(href);
}

/**
 * Builds the active-link predicate shared by the context-backed and
 * local-state sidebar variants, which differ only in where section expansion
 * state lives.
 */
function useActiveLinkCheck(): (href: Route) => boolean {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return useCallback(
    (href: Route) => {
      const tagLink = TAG_LINK_PATTERN.exec(href);
      if (tagLink) {
        const [, basePath, tagId] = tagLink;
        const isOnList = pathname === basePath || pathname === `${basePath}/`;
        return isOnList && searchParams.get('tag') === tagId;
      }
      return isActiveLink(href, pathname, searchParams);
    },
    [pathname, searchParams]
  );
}

// Dynamic navigation configuration
function useNavigationSections(): NavigationSection[] {
  const {
    data: tagsData,
    isLoading: tagsLoading,
    error: tagsError,
  } = useTags();
  const {
    data: journalTagsData,
    isLoading: journalTagsLoading,
    error: journalTagsError,
  } = useJournalTags();

  const contactItems: NavigationItem[] = [
    { label: 'All', href: '/contacts' as Route },
    { label: 'Favourites', href: '/contacts/favourites' as Route, icon: Star },
  ];

  const journalItems: NavigationItem[] = [
    { label: 'All Journals', href: '/journals' as Route },
    {
      label: 'Outdoor Logbook',
      href: '/journals/outdoor-logbook' as Route,
    },
  ];

  let contactTagTree: TagTreeNode[] | undefined;

  // Build tag tree from API data
  if (tagsData?.data && !tagsLoading && !tagsError) {
    contactTagTree = buildTagTree(tagsData.data, contactTagView);
  } else if (tagsLoading) {
    // Show loading placeholder - no href to disable the link entirely
    contactItems.push({
      label: 'Loading tags...',
      disabled: true,
    });
  }

  // Journal tags mirror the contact behaviour: a tree when loaded, a disabled
  // placeholder while loading, and silent degradation on error.
  let journalTagTree: TagTreeNode<JournalTag>[] | undefined;

  if (journalTagsData?.data && !journalTagsLoading && !journalTagsError) {
    journalTagTree = buildTagTree(journalTagsData.data, journalTagView);
  } else if (journalTagsLoading) {
    journalItems.push({
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
      renderTagTree: renderTagTreeSection(contactTagTree, {
        view: contactTagView,
        basePath: '/contacts',
        testIdPrefix: '',
        ariaLabel: 'Tags',
        wrapItem: (tag, children) => (
          <TagContextMenu tag={tag}>{children}</TagContextMenu>
        ),
      }),
      renderCreateTagDialog: props => <CreateTagDialog {...props} />,
      createTagTestId: 'create-tag-button',
    },
    {
      label: 'Journals',
      icon: BookOpen,
      defaultExpanded: false,
      items: journalItems,
      renderTagTree: renderTagTreeSection(journalTagTree, {
        view: journalTagView,
        basePath: '/journals',
        testIdPrefix: 'journal-',
        ariaLabel: 'Journal tags',
        wrapItem: (tag, children) => (
          <JournalTagContextMenu tag={tag}>{children}</JournalTagContextMenu>
        ),
      }),
      renderCreateTagDialog: props => <JournalCreateTagDialog {...props} />,
      createTagTestId: 'journal-create-tag-button',
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
 * Binds a built tree to its namespace's rendering options, or returns undefined
 * when there is nothing to render.
 */
function renderTagTreeSection<T>(
  tree: TagTreeNode<T>[] | undefined,
  options: TagTreeOptions<T>
): ((props: TagTreeRenderProps) => ReactNode) | undefined {
  if (!tree || tree.length === 0) {
    return undefined;
  }

  // Named rather than an arrow so it is not mistaken for an inline component
  // definition — it is called during the section's render, not mounted.
  return function renderBoundTagTree({
    isActiveLink: checkActiveLink,
    onNavigate,
  }: TagTreeRenderProps) {
    return (
      <TagTreeNavigation
        tree={tree}
        options={options}
        isActiveLink={checkActiveLink}
        onNavigate={onNavigate}
      />
    );
  };
}

/**
 * Everything the tree renderer needs to know about a tag namespace: how to read
 * a tag, where its links point, how its test ids are named, and any per-item
 * wrapper (contacts wrap each item in a management context menu).
 */
interface TagTreeOptions<T> {
  readonly view: TagTreeAdapter<T>;
  readonly basePath: TagFilterBasePath;
  /** Prefixed onto every test id so the two trees stay distinguishable. */
  readonly testIdPrefix: string;
  readonly ariaLabel: string;
  readonly wrapItem?: (tag: T, children: ReactNode) => ReactNode;
}

/**
 * Recursive component that renders a tag tree node with expand/collapse.
 */
function TagTreeItem<T>({
  node,
  depth,
  options,
  expandedTags,
  toggleTag,
  isActiveLink: checkActiveLink,
  onNavigate,
}: {
  readonly node: TagTreeNode<T>;
  readonly depth: number;
  readonly options: TagTreeOptions<T>;
  readonly expandedTags: Record<string, boolean>;
  readonly toggleTag: (tagId: string) => void;
  readonly isActiveLink: (href: Route) => boolean;
  readonly onNavigate?: () => void;
}) {
  const { view, basePath, testIdPrefix, wrapItem } = options;
  const { id: tagId, name: tagName } = view(node.tag);
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedTags[tagId] ?? false;
  const href = `${basePath}?tag=${tagId}` as Route;
  const isActive = checkActiveLink(href);
  const indentSizeRem = 0.75; // matches Tailwind ml-3 visually for nesting

  const row = (
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
          aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${tagName}`}
          data-testid={`${testIdPrefix}tag-toggle-${tagId}`}
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
          data-testid={`nav-link-${testIdPrefix}tag-${tagId}`}
        >
          <Tag className='mr-1.5 h-3 w-3 shrink-0' aria-hidden='true' />
          <span className='truncate'>{tagName}</span>
        </Link>
      </Button>
    </div>
  );

  return (
    <li
      className='list-none'
      style={{ marginLeft: `${depth * indentSizeRem}rem` }}
      data-testid={`${testIdPrefix}tag-tree-item-${tagId}`}
    >
      {wrapItem ? wrapItem(node.tag, row) : row}

      {/* Children (recursive) */}
      {hasChildren && isExpanded && (
        <ul aria-label={`${tagName} child tags`}>
          {node.children.map(child => (
            <TagTreeItem
              key={view(child.tag).id}
              node={child}
              depth={depth + 1}
              options={options}
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
function TagTreeNavigation<T>({
  tree,
  options,
  isActiveLink: checkActiveLink,
  onNavigate,
}: {
  readonly tree: TagTreeNode<T>[];
  readonly options: TagTreeOptions<T>;
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
    <div data-testid={`${options.testIdPrefix}tag-tree-container`}>
      <ul className='m-0 space-y-0.5 p-0' aria-label={options.ariaLabel}>
        {tree.map(node => (
          <TagTreeItem
            key={options.view(node.tag).id}
            node={node}
            depth={0}
            options={options}
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
  const { state, toggleSection } = useSidebar();
  const navigationSections = useNavigationSections();
  const checkActiveLink = useActiveLinkCheck();

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
  const navigationSections = useNavigationSections();
  const checkActiveLink = useActiveLinkCheck();
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
 * One navigation link, in the sidebar's item idiom.
 *
 * Extracted so the top-level Home entry and the items inside the collapsible
 * sections are the same control — same padding, same hover, same focus ring,
 * same `aria-current` and test id — rather than two copies that drift.
 */
function NavItemLink({
  label,
  href,
  icon: ItemIcon,
  isActive,
  onNavigate,
}: {
  readonly label: string;
  readonly href: Route;
  readonly icon?: React.ComponentType<{ className?: string }>;
  readonly isActive: boolean;
  readonly onNavigate?: () => void;
}) {
  return (
    <Button
      variant='ghost'
      size='sm'
      className={cn(
        'h-auto w-full justify-start px-2 py-1.5 font-normal',
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
        data-testid={`nav-link-${label.toLowerCase()}`}
      >
        {ItemIcon && <ItemIcon className='mr-2 h-3 w-3' aria-hidden='true' />}
        {label}
      </Link>
    </Button>
  );
}

/**
 * The home dashboard's navigation entry (wireframe gap 4).
 *
 * A top-level link rather than a section, because every section here is
 * collapsible and one that collapsed to hide its only item would be a worse
 * affordance than a plain link. The specification asks for the home page to be
 * reachable from the primary navigation as the post-sign-in default, so it must
 * not be something a user can fold away.
 */
const HOME_NAV_ITEM = {
  label: 'Home',
  href: '/' as Route,
  icon: Home,
} as const;

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
  return (
    <ScrollArea className='h-full flex-1'>
      <nav
        className='flex flex-col space-y-2 p-4'
        role='navigation'
        aria-label='Main navigation'
      >
        <NavItemLink
          {...HOME_NAV_ITEM}
          isActive={isActiveLink(HOME_NAV_ITEM.href)}
          onNavigate={onNavigate}
        />

        {navigationSections.map(section => {
          const isExpanded = expandedSections[section.label];
          const SectionIcon = section.icon;

          return (
            <div key={section.label} className='space-y-1'>
              {/* Every section is preceded by a rule: the first one now
                  follows the top-level Home link rather than starting the
                  navigation. */}
              <Separator className='my-2' />

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
                      <NavItemLink
                        key={itemKey}
                        label={item.label}
                        href={item.href}
                        icon={ItemIcon}
                        isActive={Boolean(isActive)}
                        onNavigate={onNavigate}
                      />
                    );
                  })}

                  {/* Nested tag tree */}
                  {section.renderTagTree?.({ isActiveLink, onNavigate })}

                  {/* Create Tag Button */}
                  {section.renderCreateTagDialog && (
                    <CreateTagAffordance
                      renderDialog={section.renderCreateTagDialog}
                      testId={section.createTagTestId}
                      describedBy={`section-${section.label.toLowerCase()}-header`}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </ScrollArea>
  );
}

/**
 * A section's "Create Tag" button and the dialog it opens.
 *
 * Owns its own open state so the two tag namespaces cannot open each other's
 * dialog, and so the button renders even when the section has no tags yet.
 */
function CreateTagAffordance({
  renderDialog,
  testId,
  describedBy,
}: {
  readonly renderDialog: (props: CreateTagDialogProps) => ReactNode;
  readonly testId?: string;
  /**
   * Id of the section header. Both sections show a button named "Create Tag",
   * so the description is what tells assistive tech which namespace this one
   * acts on. It is deliberately not folded into the accessible name: that would
   * both break WCAG 2.5.3's label-in-name rule and make the button collide with
   * the section header in name-based queries.
   */
  readonly describedBy: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant='ghost'
        size='sm'
        className={cn(
          'text-muted-foreground h-auto w-full justify-start px-2 py-1.5 font-normal',
          'hover:bg-accent hover:text-accent-foreground'
        )}
        onClick={() => setOpen(true)}
        data-testid={testId}
        aria-describedby={describedBy}
      >
        <Plus className='mr-2 h-3 w-3' aria-hidden='true' />
        Create Tag
      </Button>
      {renderDialog({ open, onOpenChange: setOpen })}
    </>
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
