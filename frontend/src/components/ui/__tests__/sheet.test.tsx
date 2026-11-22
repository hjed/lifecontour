/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';

import { Sheet, SheetContent, SheetTitle } from '../sheet';

function renderSheet(props: React.ComponentProps<typeof SheetContent>) {
  render(
    <Sheet open>
      <SheetContent aria-describedby={undefined} {...props}>
        <SheetTitle>Menu</SheetTitle>
      </SheetContent>
    </Sheet>
  );
  return screen.getByRole('dialog');
}

describe('SheetContent', () => {
  /**
   * Local to this app: Vega keys the side's size off `data-[side=…]:`
   * selectors, which outrank a caller's plain `w-64` and which cn() cannot
   * merge. The side's layout classes are plain, so a caller's win.
   */
  it('lets a caller set the width of a left sheet', () => {
    const sheet = renderSheet({ side: 'left', className: 'w-64 p-0' });

    expect(sheet).toHaveClass('w-64', 'left-0', 'border-r');
    expect(sheet).not.toHaveClass('w-3/4');
    expect(sheet.className).not.toMatch(/data-\[side=[a-z]+\]:w-/);
  });

  it('lets a caller set the max width of a right sheet', () => {
    const sheet = renderSheet({ className: 'w-full sm:max-w-md' });

    expect(sheet).toHaveClass('w-full', 'sm:max-w-md', 'right-0');
    expect(sheet).not.toHaveClass('sm:max-w-sm');
    expect(sheet.className).not.toMatch(/data-\[side=[a-z]+\]:sm:max-w-/);
  });

  it('keeps the default size when the caller sets none', () => {
    expect(renderSheet({ side: 'right' })).toHaveClass('w-3/4', 'sm:max-w-sm');
  });
});
