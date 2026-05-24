/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import {
  SidebarProvider,
  useSidebar,
  useSidebarAvailable,
} from '../SidebarContext';

// Mock localStorage
const mockLocalStorage = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};

Object.defineProperty(window, 'localStorage', {
  value: mockLocalStorage,
});

// Test component that uses the sidebar context
function TestComponent() {
  const { state, toggleSidebar, openSidebar, closeSidebar, toggleSection } =
    useSidebar();

  return (
    <div>
      <div data-testid='sidebar-open'>{state.isOpen.toString()}</div>
      <div data-testid='contacts-expanded'>
        {state.expandedSections.Contacts?.toString()}
      </div>
      <div data-testid='journals-expanded'>
        {state.expandedSections.Journals?.toString()}
      </div>

      <button onClick={toggleSidebar} data-testid='toggle-sidebar'>
        Toggle Sidebar
      </button>
      <button onClick={openSidebar} data-testid='open-sidebar'>
        Open Sidebar
      </button>
      <button onClick={closeSidebar} data-testid='close-sidebar'>
        Close Sidebar
      </button>
      <button
        onClick={() => toggleSection('Contacts')}
        data-testid='toggle-contacts'
      >
        Toggle Contacts
      </button>
      <button
        onClick={() => toggleSection('Journals')}
        data-testid='toggle-journals'
      >
        Toggle Journals
      </button>
    </div>
  );
}

// Test component for checking availability
function AvailabilityTestComponent() {
  const isAvailable = useSidebarAvailable();
  return <div data-testid='sidebar-available'>{isAvailable.toString()}</div>;
}

describe('SidebarContext', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    mockLocalStorage.getItem.mockReturnValue(null);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const renderWithProvider = (ui: React.ReactNode, props?: any) => {
    const result = render(<SidebarProvider {...props}>{ui}</SidebarProvider>);
    act(() => {
      jest.runAllTimers();
    });
    return result;
  };

  describe('SidebarProvider', () => {
    it('provides default state when no localStorage data', () => {
      renderWithProvider(<TestComponent />);

      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('false');
      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent('true');
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent(
        'false'
      );
    });

    it('loads state from localStorage', () => {
      mockLocalStorage.getItem.mockReturnValue(
        JSON.stringify({
          expandedSections: { Contacts: false, Journals: true },
        })
      );

      renderWithProvider(<TestComponent />);

      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent(
        'false'
      );
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent('true');
    });

    it('handles invalid localStorage data gracefully', () => {
      mockLocalStorage.getItem.mockReturnValue('invalid-json');
      const consoleSpy = jest.spyOn(console, 'warn').mockImplementation();

      renderWithProvider(<TestComponent />);

      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent('true');
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent(
        'false'
      );
      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to load sidebar state from localStorage:',
        expect.any(Error)
      );

      consoleSpy.mockRestore();
    });

    it('uses custom default expanded sections', () => {
      const customDefaults = { Contacts: false, Journals: true };

      renderWithProvider(<TestComponent />, { defaultExpandedSections: customDefaults });

      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent(
        'false'
      );
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent('true');
    });
  });

  describe('sidebar state management', () => {
    it('toggles sidebar open/closed', () => {
      renderWithProvider(<TestComponent />);

      const toggleButton = screen.getByTestId('toggle-sidebar');

      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('false');

      fireEvent.click(toggleButton);
      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('true');

      fireEvent.click(toggleButton);
      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('false');
    });

    it('opens sidebar', () => {
      renderWithProvider(<TestComponent />);

      const openButton = screen.getByTestId('open-sidebar');

      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('false');

      fireEvent.click(openButton);
      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('true');
    });

    it('closes sidebar', () => {
      renderWithProvider(<TestComponent />);

      const openButton = screen.getByTestId('open-sidebar');
      const closeButton = screen.getByTestId('close-sidebar');

      // First open it
      fireEvent.click(openButton);
      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('true');

      // Then close it
      fireEvent.click(closeButton);
      expect(screen.getByTestId('sidebar-open')).toHaveTextContent('false');
    });

    it('toggles section expansion', () => {
      renderWithProvider(<TestComponent />);

      const toggleContactsButton = screen.getByTestId('toggle-contacts');
      const toggleJournalsButton = screen.getByTestId('toggle-journals');

      // Contacts starts expanded, Journals starts collapsed
      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent('true');
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent(
        'false'
      );

      // Toggle contacts (should collapse)
      fireEvent.click(toggleContactsButton);
      expect(screen.getByTestId('contacts-expanded')).toHaveTextContent(
        'false'
      );

      // Toggle journals (should expand)
      fireEvent.click(toggleJournalsButton);
      expect(screen.getByTestId('journals-expanded')).toHaveTextContent('true');
    });
  });

  describe('localStorage persistence', () => {
    it('saves state to localStorage when state changes', async () => {
      renderWithProvider(<TestComponent />);

      const toggleContactsButton = screen.getByTestId('toggle-contacts');

      await act(async () => {
        fireEvent.click(toggleContactsButton);
      });

      expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
        'sidebar-state',
        JSON.stringify({
          expandedSections: { Contacts: false, Journals: false },
        })
      );
    });

    it('handles localStorage save errors gracefully', async () => {
      mockLocalStorage.setItem.mockImplementation(() => {
        throw new Error('Storage quota exceeded');
      });
      const consoleSpy = jest.spyOn(console, 'warn').mockImplementation();

      renderWithProvider(<TestComponent />);

      const toggleContactsButton = screen.getByTestId('toggle-contacts');

      await act(async () => {
        fireEvent.click(toggleContactsButton);
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to save sidebar state to localStorage:',
        expect.any(Error)
      );

      consoleSpy.mockRestore();
    });
  });

  describe('useSidebarAvailable', () => {
    it('returns true when context is available', () => {
      renderWithProvider(<AvailabilityTestComponent />);

      expect(screen.getByTestId('sidebar-available')).toHaveTextContent('true');
    });

    it('returns false when context is not available', () => {
      render(<AvailabilityTestComponent />);

      expect(screen.getByTestId('sidebar-available')).toHaveTextContent(
        'false'
      );
    });
  });

  describe('error handling', () => {
    it('throws error when useSidebar is used outside provider', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      expect(() => {
        render(<TestComponent />);
      }).toThrow('useSidebar must be used within a SidebarProvider');

      consoleSpy.mockRestore();
    });
  });
});
