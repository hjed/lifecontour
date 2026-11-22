/**
 * @jest-environment jsdom
 */

import { render } from '@testing-library/react';

import {
  Select,
  SelectContent,
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
});
