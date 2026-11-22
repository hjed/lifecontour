/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';

import { Popover, PopoverContent, PopoverTrigger } from '../popover';

describe('PopoverContent', () => {
  /**
   * Local to this app, kept across shadcn regenerations: a popover taller
   * than the screen (the two-month date-range picker on a phone) scrolls
   * within the space Radix measures instead of running off the bottom.
   */
  it('scrolls within the height available to it', () => {
    render(
      <Popover open>
        <PopoverTrigger>open</PopoverTrigger>
        <PopoverContent data-testid='content'>tall content</PopoverContent>
      </Popover>
    );

    const content = screen.getByTestId('content');
    expect(content).toHaveClass(
      'max-h-(--radix-popover-content-available-height)'
    );
    expect(content).toHaveClass('overflow-y-auto');
  });
});
