'use client';

/**
 * Sidebar context for managing sidebar state across the application.
 *
 * Provides global state management for sidebar visibility, expanded sections,
 * and persistence across page navigation.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useMemo,
  useCallback,
  ReactNode,
} from 'react';

interface SidebarState {
  isOpen: boolean;
  expandedSections: Record<string, boolean>;
}

interface SidebarContextType {
  state: SidebarState;
  toggleSidebar: () => void;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSection: (sectionLabel: string) => void;
  setExpandedSections: (sections: Record<string, boolean>) => void;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

const SIDEBAR_STORAGE_KEY = 'sidebar-state';

interface SidebarProviderProps {
  readonly children: ReactNode;
  readonly defaultExpandedSections?: Record<string, boolean>;
}

/**
 * Default expanded sections configuration
 */
const DEFAULT_EXPANDED_SECTIONS: Record<string, boolean> = {
  Contacts: true,
  Journals: false,
};

/**
 * Load initial sidebar state (always uses defaults for SSR hydration)
 */
function loadSidebarState(
  defaultExpandedSections: Record<string, boolean>
): SidebarState {
  return {
    isOpen: false,
    expandedSections: defaultExpandedSections,
  };
}

export function SidebarProvider({
  children,
  defaultExpandedSections = DEFAULT_EXPANDED_SECTIONS,
}: SidebarProviderProps) {
  const [state, setState] = useState<SidebarState>(() =>
    loadSidebarState(defaultExpandedSections)
  );

  const [isClient, setIsClient] = useState(false);

  // Load saved state from localStorage after hydration
  useEffect(() => {
    try {
      const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        setState(prev => ({
          ...prev,
          expandedSections: {
            ...defaultExpandedSections,
            ...parsed.expandedSections,
          },
        }));
      }
    } catch (error) {
      console.warn('Failed to load sidebar state from localStorage:', error);
    }
    setIsClient(true);
  }, [defaultExpandedSections]);

  // Save expandedSections to localStorage whenever they change
  useEffect(() => {
    if (isClient) {
      try {
        localStorage.setItem(
          SIDEBAR_STORAGE_KEY,
          JSON.stringify({
            expandedSections: state.expandedSections,
            // Don't persist isOpen state - always start closed
          })
        );
      } catch (error) {
        console.warn('Failed to save sidebar state to localStorage:', error);
      }
    }
  }, [state.expandedSections, isClient]);

  const toggleSidebar = useCallback(() => {
    setState(prev => ({ ...prev, isOpen: !prev.isOpen }));
  }, []);

  const openSidebar = useCallback(() => {
    setState(prev => ({ ...prev, isOpen: true }));
  }, []);

  const closeSidebar = useCallback(() => {
    setState(prev => ({ ...prev, isOpen: false }));
  }, []);

  const toggleSection = useCallback((sectionLabel: string) => {
    setState(prev => ({
      ...prev,
      expandedSections: {
        ...prev.expandedSections,
        [sectionLabel]: !prev.expandedSections[sectionLabel],
      },
    }));
  }, []);

  const setExpandedSections = useCallback(
    (sections: Record<string, boolean>) => {
      setState(prev => ({
        ...prev,
        expandedSections: sections,
      }));
    },
    []
  );

  const contextValue: SidebarContextType = useMemo(
    () => ({
      state,
      toggleSidebar,
      openSidebar,
      closeSidebar,
      toggleSection,
      setExpandedSections,
    }),
    [
      state,
      toggleSidebar,
      openSidebar,
      closeSidebar,
      toggleSection,
      setExpandedSections,
    ]
  );

  return (
    <SidebarContext.Provider value={contextValue}>
      {children}
    </SidebarContext.Provider>
  );
}

/**
 * Hook to use sidebar context
 */
export function useSidebar(): SidebarContextType {
  const context = useContext(SidebarContext);
  if (context === undefined) {
    throw new Error('useSidebar must be used within a SidebarProvider');
  }
  return context;
}

/**
 * Hook to check if sidebar is available (for conditional rendering)
 */
export function useSidebarAvailable(): boolean {
  const context = useContext(SidebarContext);
  return context !== undefined;
}
