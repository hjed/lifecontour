import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouteSelector } from '../RouteSelector';
import * as routesApi from '@/lib/api/routes';

jest.mock('@/lib/api/routes', () => ({
  useRoutes: jest.fn(),
}));

const ROUTE_SELECTOR_REF_WARNING_PATTERN =
  /Function components cannot be given refs|Accessing element\.ref was removed in React 19/i;

describe('RouteSelector ref handling', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    globalThis.HTMLElement.prototype.scrollIntoView = jest.fn();
    globalThis.HTMLElement.prototype.hasPointerCapture = jest.fn();
    globalThis.HTMLElement.prototype.releasePointerCapture = jest.fn();
  });

  it('does not emit ref warnings when opening the popover', async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);

    try {
      (routesApi.useRoutes as jest.Mock).mockReturnValue({
        data: { data: [{ id: '1', attributes: { name: 'Test Route 1' } }] },
        isLoading: false,
      });

      render(<RouteSelector onChange={jest.fn()} />);

      await user.click(screen.getByRole('combobox'));

      expect(
        await screen.findByPlaceholderText('Search routes...')
      ).toBeInTheDocument();

      const refWarnings = consoleErrorSpy.mock.calls
        .map(call => call.map(String).join(' '))
        .filter(message => ROUTE_SELECTOR_REF_WARNING_PATTERN.test(message));

      expect(refWarnings).toHaveLength(0);
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });
});
