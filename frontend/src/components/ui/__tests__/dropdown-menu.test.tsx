import { render, screen } from '@testing-library/react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

describe('DropdownMenuContent', () => {
  // Most triggers are icon buttons (SyncControls, row actions); a menu
  // pinned to the trigger's width would squeeze long labels into 128px.
  it('sizes to its items, not to the trigger', () => {
    render(
      <DropdownMenu open>
        <DropdownMenuTrigger aria-label='Sync options'>v</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>Full Sync (Comprehensive)</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );

    const menu = screen.getByRole('menu');
    expect(menu.className).not.toContain('--radix-dropdown-menu-trigger-width');
    expect(menu).toHaveClass('min-w-32');
  });
});
