/**
 * @jest-environment jsdom
 */

import { render } from '@testing-library/react';

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../select';

describe('SelectContent', () => {
  /**
   * Local to this app, kept across shadcn regenerations: the list opens as a
   * popper below the trigger. Vega defaults to `item-aligned`, which opens
   * the list over the trigger so the tap that opened it can pick an option.
   */
  it('opens as a popper below the trigger by default', () => {
    render(
      <Select open defaultValue='a'>
        <SelectTrigger aria-label='Pick'>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value='a'>A</SelectItem>
          <SelectItem value='b'>B</SelectItem>
        </SelectContent>
      </Select>
    );

    expect(
      document.querySelector('[data-radix-popper-content-wrapper]')
    ).not.toBeNull();
  });

  /**
   * Local to this app: Vega pads SelectGroup instead of the list, but most
   * callers render items without a group, so the inset lives on the
   * viewport and a group adds none of its own.
   */
  it('insets the options whether or not they are grouped', () => {
    render(
      <Select open defaultValue='a'>
        <SelectTrigger aria-label='Pick'>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value='a'>A</SelectItem>
          <SelectGroup data-testid='group'>
            <SelectItem value='b'>B</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    );

    expect(document.querySelector('[data-radix-select-viewport]')).toHaveClass(
      'p-1'
    );
    expect(document.querySelector('[data-slot=select-group]')).not.toHaveClass(
      'p-1'
    );
  });
});
