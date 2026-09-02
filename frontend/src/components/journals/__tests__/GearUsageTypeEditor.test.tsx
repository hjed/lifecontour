/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import { GearUsageTypeEditor } from '../type-editors/GearUsageTypeEditor';
import { renderWithProviders } from '@/test-utils';
import * as gearItemsApi from '@/lib/api/gearItems';
import * as integrationsApi from '@/lib/api/integrations';

jest.mock('@/lib/api/gearItems', () => ({
  getGearItems: jest.fn(),
  createGearItem: jest.fn(),
}));

jest.mock('@/lib/api/integrations', () => ({
  useIntegrations: jest.fn(),
}));

const mockGetGearItems = gearItemsApi.getGearItems as jest.Mock;
const mockUseIntegrations = integrationsApi.useIntegrations as jest.Mock;

function integrationsResponse(status: 'connected' | 'disconnected') {
  return {
    data: {
      data: [
        {
          id: 'snipeit',
          type: 'integration',
          attributes: {
            name: 'Snipe-IT',
            status,
            capabilities: ['gear_sync'],
            needs_reauth: false,
            needs_reconsent: false,
            sync_summary: {
              sync_count: 0,
              error_count: 0,
              last_sync_time: null,
            },
          },
        },
      ],
    },
    isLoading: false,
    error: null,
  };
}

describe('GearUsageTypeEditor — Snipe-IT buffer dates', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetGearItems.mockResolvedValue([
      { id: 'g1', name: 'Test Climbing Rope' },
    ]);
  });

  it('shows the buffer date inputs when Snipe-IT is connected', async () => {
    mockUseIntegrations.mockReturnValue(integrationsResponse('connected'));

    renderWithProviders(<GearUsageTypeEditor createMode />);

    expect(
      await screen.findByTestId('gear-usage-type-editor')
    ).toBeInTheDocument();
    expect(screen.getByTestId('gear-item-selector')).toBeInTheDocument();
    expect(screen.getByTestId('checkout-date-input')).toBeInTheDocument();
    expect(screen.getByTestId('checkin-date-input')).toBeInTheDocument();
    expect(screen.getByLabelText('Checkout Date (Buffer)')).toBeEnabled();
    expect(screen.getByLabelText('Checkin Date (Buffer)')).toBeEnabled();
  });

  it('hides the buffer date inputs when Snipe-IT is disconnected', async () => {
    mockUseIntegrations.mockReturnValue(integrationsResponse('disconnected'));

    renderWithProviders(<GearUsageTypeEditor createMode />);

    expect(
      await screen.findByTestId('gear-usage-type-editor')
    ).toBeInTheDocument();
    // The gear selector is still offered — only the Snipe-IT-backed buffer
    // dates are withheld.
    expect(screen.getByTestId('gear-item-selector')).toBeInTheDocument();
    expect(screen.queryByTestId('checkout-date-input')).not.toBeInTheDocument();
    expect(screen.queryByTestId('checkin-date-input')).not.toBeInTheDocument();
  });
});
