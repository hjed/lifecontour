/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';

import { Button, buttonVariants } from '../button';

/**
 * The Vega sizes are denser than the 40px the app had, so the touch-target
 * floor lives here: `lg` never drops below 40px (the login page's OAuth
 * buttons are asserted at ≥ 40px on desktop at phone width), and the default
 * and icon sizes grow to 40px on a coarse pointer.
 */
describe('Button (shadcn Vega)', () => {
  it('keeps lg at 40px for every pointer', () => {
    expect(buttonVariants({ size: 'lg' })).toContain('h-10');
  });

  it('grows the default and icon sizes to 40px on touch screens', () => {
    expect(buttonVariants()).toContain('touch-target');
    expect(buttonVariants({ size: 'icon' })).toContain('touch-target-square');
  });

  it('offers the extra Vega sizes', () => {
    expect(buttonVariants({ size: 'icon-sm' })).toContain('size-8');
    expect(buttonVariants({ size: 'xs' })).toContain('h-6');
  });

  it('tints the destructive variant instead of filling it', () => {
    const classes = buttonVariants({ variant: 'destructive' });

    expect(classes).toContain('bg-destructive/10');
    expect(classes).toContain('text-destructive');
    expect(classes).not.toContain('text-white');
  });

  it('lets a call site override the size', () => {
    render(
      <Button size='icon' className='size-11'>
        x
      </Button>
    );

    const button = screen.getByRole('button');
    expect(button).toHaveClass('size-11');
    expect(button).not.toHaveClass('size-9');
  });

  it('forwards a ref as a plain prop', () => {
    const ref = { current: null as HTMLButtonElement | null };

    render(<Button ref={ref}>x</Button>);

    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });
});
