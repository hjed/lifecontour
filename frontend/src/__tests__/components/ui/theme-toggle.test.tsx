/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { ThemeProvider } from 'next-themes';
import { ThemeToggle } from '@/components/ui/theme-toggle';

// Mock next-themes
const mockSetTheme = jest.fn();
const mockTheme = 'light';

jest.mock('next-themes', () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
  useTheme: () => ({
    theme: mockTheme,
    setTheme: mockSetTheme,
  }),
}));

describe('ThemeToggle', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders theme toggle button', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const toggleButton = screen.getByTestId('theme-toggle');
    expect(toggleButton).toBeInTheDocument();
    expect(toggleButton).toHaveAttribute('aria-label', 'Toggle theme');
  });

  it('renders dropdown menu trigger with correct attributes', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const toggleButton = screen.getByTestId('theme-toggle');
    expect(toggleButton).toHaveAttribute('aria-haspopup', 'menu');
    expect(toggleButton).toHaveAttribute('aria-expanded', 'false');
  });

  it('has correct theme icons', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    // Check for sun and moon icons (they should be present in the DOM)
    const sunIcon = document.querySelector('.lucide-sun');
    const moonIcon = document.querySelector('.lucide-moon');

    expect(sunIcon).toBeInTheDocument();
    expect(moonIcon).toBeInTheDocument();
  });

  it('uses next-themes useTheme hook', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    // The component should render without errors, indicating useTheme is working
    expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
  });

  it('has proper accessibility attributes', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    const toggleButton = screen.getByTestId('theme-toggle');
    expect(toggleButton).toHaveAttribute('aria-label', 'Toggle theme');

    // Check for screen reader text
    expect(screen.getByText('Toggle theme')).toHaveClass('sr-only');
  });
});
