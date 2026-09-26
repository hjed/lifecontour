/**
 * @jest-environment jsdom
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

jest.mock('sonner', () => ({
  toast: { error: jest.fn(), success: jest.fn() },
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

const GEAR = [
  { id: 'g1', name: 'Test Climbing Rope' },
  { id: 'g2', name: 'Harness' },
  { id: 'g3', name: 'Helmet' },
];

async function addGearItem(
  user: ReturnType<typeof userEvent.setup>,
  name: string
) {
  await user.click(screen.getByTestId('gear-item-selector'));
  await user.click(await screen.findByRole('option', { name }));
}

function rows() {
  return screen.queryAllByTestId('gear-usage-item-row');
}

describe('GearUsageTypeEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetGearItems.mockResolvedValue(GEAR);
    mockUseIntegrations.mockReturnValue(integrationsResponse('disconnected'));
  });

  describe('Snipe-IT buffer dates', () => {
    it('shows each item its own buffer dates when Snipe-IT is connected', async () => {
      mockUseIntegrations.mockReturnValue(integrationsResponse('connected'));
      const user = userEvent.setup();

      renderWithProviders(<GearUsageTypeEditor createMode />);
      await addGearItem(user, 'Harness');
      await addGearItem(user, 'Helmet');

      expect(rows()).toHaveLength(2);
      for (const row of rows()) {
        expect(within(row).getByTestId('checkout-date-input')).toBeEnabled();
        expect(within(row).getByTestId('checkin-date-input')).toBeEnabled();
      }
    });

    it('hides the buffer dates when Snipe-IT is disconnected', async () => {
      const user = userEvent.setup();

      renderWithProviders(<GearUsageTypeEditor createMode />);
      await addGearItem(user, 'Harness');

      // The gear is still listed — only the Snipe-IT-backed dates are withheld.
      expect(rows()).toHaveLength(1);
      expect(
        screen.queryByTestId('checkout-date-input')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('checkin-date-input')
      ).not.toBeInTheDocument();
    });
  });

  it('saves every gear item added, in order', async () => {
    const user = userEvent.setup();
    const onSave = jest.fn().mockResolvedValue(undefined);

    renderWithProviders(
      <GearUsageTypeEditor data={{ items: [] }} onSave={onSave} />
    );
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await addGearItem(user, 'Harness');
    await addGearItem(user, 'Test Climbing Rope');
    await user.click(screen.getByRole('button', { name: /save/i }));

    expect(onSave).toHaveBeenCalledWith({
      items: [{ gear_item_id: 'g2' }, { gear_item_id: 'g1' }],
    });
  });

  it('shows gear already listed as added rather than hiding it', async () => {
    // Hidden, a search for it would find nothing and offer to create it again.
    const user = userEvent.setup();

    renderWithProviders(
      <GearUsageTypeEditor
        createMode
        data={{ items: [{ gear_item_id: 'g1' }] }}
      />
    );
    await user.click(await screen.findByTestId('gear-item-selector'));

    expect(
      await screen.findByRole('option', { name: 'Harness' })
    ).not.toHaveAttribute('aria-disabled', 'true');
    const listed = screen.getByRole('option', { name: /Test Climbing Rope/ });
    expect(listed).toHaveAttribute('aria-disabled', 'true');
    expect(listed).toHaveTextContent('Added');
  });

  it('removes one item and keeps the others', async () => {
    const user = userEvent.setup();
    const onSave = jest.fn().mockResolvedValue(undefined);

    renderWithProviders(
      <GearUsageTypeEditor
        data={{
          items: [
            { gear_item_id: 'g1', checkin_date: '2026-05-03T08:00:00.000Z' },
            { gear_item_id: 'g2' },
          ],
        }}
        onSave={onSave}
      />
    );
    await user.click(await screen.findByRole('button', { name: /edit/i }));
    await user.click(
      await screen.findByRole('button', { name: 'Remove Harness' })
    );
    await user.click(screen.getByRole('button', { name: /save/i }));

    expect(onSave).toHaveBeenCalledWith({
      items: [{ gear_item_id: 'g1', checkin_date: '2026-05-03T08:00:00.000Z' }],
    });
  });

  it('refuses to save with no gear item', async () => {
    const user = userEvent.setup();
    const onSave = jest.fn();

    renderWithProviders(
      <GearUsageTypeEditor data={{ items: [] }} onSave={onSave} />
    );
    await user.click(screen.getByRole('button', { name: /edit/i }));
    await user.click(screen.getByRole('button', { name: /save/i }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it('lists every gear item used when not editing', async () => {
    renderWithProviders(
      <GearUsageTypeEditor
        data={{ items: [{ gear_item_id: 'g1' }, { gear_item_id: 'g3' }] }}
      />
    );

    const summary = await screen.findByTestId('gear-usage-summary');
    expect(
      await within(summary).findByText('Test Climbing Rope')
    ).toBeVisible();
    expect(within(summary).getByText('Helmet')).toBeVisible();
  });

  it('reads the older single-item shape as one item', async () => {
    renderWithProviders(<GearUsageTypeEditor data={{ gear_item_id: 'g2' }} />);

    const summary = await screen.findByTestId('gear-usage-summary');
    expect(await within(summary).findByText('Harness')).toBeVisible();
  });
});
